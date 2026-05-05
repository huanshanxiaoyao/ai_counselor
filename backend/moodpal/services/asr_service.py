from __future__ import annotations

import asyncio
import gzip
import json
import logging
import uuid
import wave
from io import BytesIO

import websockets
from django.conf import settings

logger = logging.getLogger(__name__)

_WS_URL = 'wss://openspeech.bytedance.com/api/v2/asr'
_DEFAULT_CLUSTER = 'volcengine_input_common'
_SUCCESS_CODE = 1000
_RECV_TIMEOUT = 30
_MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 10 MB

# ── Binary protocol constants (matches Volcengine SDK) ──────────────────────
_PROTOCOL_VERSION = 0b0001
_CLIENT_FULL_REQUEST = 0b0001
_CLIENT_AUDIO_ONLY = 0b0010
_SERVER_FULL_RESPONSE = 0b1001
_SERVER_ACK = 0b1011
_SERVER_ERROR = 0b1111
_NO_SEQUENCE = 0b0000
_NEG_SEQUENCE = 0b0010
_JSON = 0b0001
_GZIP = 0b0001


class ASRError(Exception):
    pass


def is_asr_configured() -> bool:
    return bool(
        getattr(settings, 'DOUBAO_ASR_APP_ID', '')
        and getattr(settings, 'DOUBAO_ASR_ACCESS_TOKEN', '')
    )


# ── Protocol helpers ─────────────────────────────────────────────────────────

def _make_header(msg_type: int, seq_flags: int = _NO_SEQUENCE) -> bytearray:
    h = bytearray(4)
    h[0] = (_PROTOCOL_VERSION << 4) | 0b0001  # header_size = 1 (4 bytes)
    h[1] = (msg_type << 4) | seq_flags
    h[2] = (_JSON << 4) | _GZIP
    h[3] = 0x00
    return h


def _pack_payload(header: bytearray, payload_bytes: bytes) -> bytes:
    msg = bytearray(header)
    msg.extend(len(payload_bytes).to_bytes(4, 'big'))
    msg.extend(payload_bytes)
    return bytes(msg)


def _parse_response(data: bytes) -> dict:
    header_size = (data[0] & 0x0F) * 4
    msg_type = data[1] >> 4
    compression = data[2] & 0x0F
    payload = data[header_size:]
    result: dict = {}

    if msg_type == _SERVER_FULL_RESPONSE:
        size = int.from_bytes(payload[:4], 'big', signed=True)
        raw = payload[4:4 + size]
    elif msg_type == _SERVER_ACK:
        result['seq'] = int.from_bytes(payload[:4], 'big', signed=True)
        if len(payload) < 8:
            return result
        size = int.from_bytes(payload[4:8], 'big', signed=False)
        raw = payload[8:8 + size]
    elif msg_type == _SERVER_ERROR:
        result['error_code'] = int.from_bytes(payload[:4], 'big', signed=False)
        size = int.from_bytes(payload[4:8], 'big', signed=False)
        raw = payload[8:8 + size]
    else:
        return result

    if compression == _GZIP:
        raw = gzip.decompress(raw)
    result['payload_msg'] = json.loads(raw.decode('utf-8'))
    return result


# ── WAV chunking ─────────────────────────────────────────────────────────────

def _wav_file_chunks(audio_bytes: bytes, seg_ms: int = 15000):
    """Yield (chunk, is_last) slicing full WAV bytes (header included).

    Mirrors Volcengine SDK: segment_size computed from audio params but slicing
    applied to the whole file buffer so the first chunk carries the WAV header.
    """
    with BytesIO(audio_bytes) as f:
        wf = wave.open(f, 'rb')
        nchannels, sampwidth, framerate, _ = wf.getparams()[:4]

    chunk_size = nchannels * sampwidth * framerate * seg_ms // 1000
    total = len(audio_bytes)
    offset = 0
    while offset < total:
        end = min(offset + chunk_size, total)
        is_last = end >= total
        yield audio_bytes[offset:end], is_last
        offset = end
        if is_last:
            break


# ── WebSocket transcription ──────────────────────────────────────────────────

async def _transcribe_ws(audio_bytes: bytes, app_id: str, token: str, cluster: str) -> str:
    req_id = str(uuid.uuid4())
    logger.info('ASR start reqid=%s audio_bytes=%d', req_id, len(audio_bytes))

    req_meta = {
        'app': {'appid': app_id, 'cluster': cluster, 'token': token},
        'user': {'uid': 'moodpal_user'},
        'request': {
            'reqid': req_id,
            'nbest': 1,
            'workflow': 'audio_in,resample,partition,vad,fe,decode,itn,nlu_punctuate',
            'show_language': False,
            'show_utterances': False,
            'result_type': 'full',
            'sequence': 1,
        },
        'audio': {
            'format': 'wav',
            'rate': 16000,
            'language': 'zh-CN',
            'bits': 16,
            'channel': 1,
            'codec': 'raw',
        },
    }

    full_payload = gzip.compress(json.dumps(req_meta).encode('utf-8'))
    full_msg = _pack_payload(_make_header(_CLIENT_FULL_REQUEST), full_payload)
    # websockets >=11 uses additional_headers; <11 used extra_headers
    auth_header = {'Authorization': f'Bearer; {token}'}

    logger.info('ASR connecting to %s', _WS_URL)
    # websockets >=11 uses additional_headers; <=10 uses extra_headers
    _ws_version = tuple(int(x) for x in websockets.__version__.split('.')[:2])
    _connect_kwargs: dict = {
        'max_size': 1_000_000_000,
        'ping_interval': None,
        ('additional_headers' if _ws_version >= (11, 0) else 'extra_headers'): auth_header,
    }
    async with websockets.connect(_WS_URL, **_connect_kwargs) as ws:
        # Send metadata frame
        await ws.send(full_msg)
        raw = await asyncio.wait_for(ws.recv(), timeout=_RECV_TIMEOUT)
        init = _parse_response(raw)
        init_code = (init.get('payload_msg') or {}).get('code', _SUCCESS_CODE)
        logger.info('ASR init response code=%s', init_code)
        if init_code != _SUCCESS_CODE:
            msg_text = (init.get('payload_msg') or {}).get('message', '')
            raise ASRError(f'asr_init_error:{init_code}:{msg_text}')

        # Stream audio chunks
        last_result: dict = init
        chunk_count = 0
        for chunk, is_last in _wav_file_chunks(audio_bytes):
            chunk_count += 1
            seq = _NEG_SEQUENCE if is_last else _NO_SEQUENCE
            hdr = _make_header(_CLIENT_AUDIO_ONLY, seq)
            audio_payload = _pack_payload(hdr, gzip.compress(chunk))
            await ws.send(audio_payload)
            raw = await asyncio.wait_for(ws.recv(), timeout=_RECV_TIMEOUT)
            last_result = _parse_response(raw)
            logger.info('ASR chunk %d sent is_last=%s seq_in_resp=%s', chunk_count, is_last, last_result.get('seq'))

    payload = last_result.get('payload_msg') or {}
    code = payload.get('code', _SUCCESS_CODE)
    logger.info('ASR final payload keys=%s code=%s', list(payload.keys()), code)
    if code != _SUCCESS_CODE:
        raise ASRError(f'asr_error:{code}:{payload.get("message", "")}')

    results = payload.get('result') or []
    if results and isinstance(results, list):
        text = results[0].get('text') or results[0].get('punc') or ''
    else:
        utterances = payload.get('utterances') or []
        text = ''.join(u.get('text', '') for u in utterances)

    logger.info('ASR success text_len=%d preview=%r', len(text), text[:40])
    return text.strip()


# ── Public entry point ───────────────────────────────────────────────────────

def transcribe_audio(audio_bytes: bytes, mime_type: str) -> str:
    """Transcribe WAV audio using Doubao (Volcengine) streaming WebSocket ASR."""
    logger.info('ASR transcribe_audio called bytes=%d mime=%s', len(audio_bytes) if audio_bytes else 0, mime_type)

    if not is_asr_configured():
        raise ASRError('asr_not_configured')
    if not audio_bytes:
        raise ASRError('empty_audio')
    if len(audio_bytes) > _MAX_AUDIO_BYTES:
        raise ASRError('audio_too_large')
    if audio_bytes[:4] != b'RIFF':
        logger.warning('ASR invalid WAV header: %r', audio_bytes[:8])
        raise ASRError('invalid_wav: frontend must send 16kHz mono WAV')

    app_id = settings.DOUBAO_ASR_APP_ID
    token = settings.DOUBAO_ASR_ACCESS_TOKEN
    cluster = getattr(settings, 'DOUBAO_ASR_CLUSTER', _DEFAULT_CLUSTER)

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_transcribe_ws(audio_bytes, app_id, token, cluster))
    except ASRError:
        raise
    except asyncio.TimeoutError:
        raise ASRError('asr_timeout')
    except Exception as exc:
        logger.warning('ASR WebSocket error: %s %s', type(exc).__name__, exc)
        raise ASRError(f'asr_ws_error:{type(exc).__name__}')
    except BaseException as exc:
        # asyncio.CancelledError is BaseException (not Exception) in Python 3.9+
        logger.warning('ASR BaseException: %s %s', type(exc).__name__, exc)
        raise ASRError(f'asr_ws_error:{type(exc).__name__}')
    finally:
        loop.close()
