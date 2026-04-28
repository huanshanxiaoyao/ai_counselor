from pathlib import Path

from django.core.management.base import BaseCommand

from backend.moodpal_eval.services.case_import_service import (
    import_real_cases_from_file,
    import_synthetic_cases_from_dir,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


class Command(BaseCommand):
    help = 'Import MoodPal eval cases from real and synthetic sources.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source-file',
            default=str(REPO_ROOT / 'docs/moodpal/soulchat_mulit_turn_packing.json'),
            help='Path to the real-case JSON file.',
        )
        parser.add_argument(
            '--synthetic-dir',
            default=str(REPO_ROOT / 'backend/moodpal_eval/fixtures/extreme_cases'),
            help='Directory containing synthetic extreme case JSON files.',
        )
        parser.add_argument('--skip-real', action='store_true', help='Skip importing real dataset cases.')
        parser.add_argument('--skip-synthetic', action='store_true', help='Skip importing synthetic extreme cases.')

    def handle(self, *args, **options):
        source_file = Path(options['source_file'])
        synthetic_dir = Path(options['synthetic_dir'])
        summary = {}

        if not options['skip_real']:
            real_stats = import_real_cases_from_file(source_file)
            summary['real'] = real_stats
            self.stdout.write(self.style.SUCCESS(f'real cases imported: {real_stats}'))

        if not options['skip_synthetic']:
            synthetic_stats = import_synthetic_cases_from_dir(synthetic_dir)
            summary['synthetic'] = synthetic_stats
            self.stdout.write(self.style.SUCCESS(f'synthetic cases imported: {synthetic_stats}'))

        if not summary:
            self.stdout.write(self.style.WARNING('nothing imported'))
