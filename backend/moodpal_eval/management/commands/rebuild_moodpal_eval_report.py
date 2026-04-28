from django.core.management.base import BaseCommand, CommandError

from backend.moodpal_eval.services.report_service import rebuild_run_report
from backend.moodpal_eval.services.run_service import get_run


class Command(BaseCommand):
    help = 'Rebuild summary report for a MoodPal eval run.'

    def add_arguments(self, parser):
        parser.add_argument('--run-id', required=True, help='MoodPalEvalRun UUID.')

    def handle(self, *args, **options):
        run_id = options['run_id']
        try:
            run = get_run(run_id)
        except Exception as exc:
            raise CommandError(f'run not found: {run_id}') from exc

        rebuilt = rebuild_run_report(run)
        self.stdout.write(
            self.style.SUCCESS(
                f'run={rebuilt.id} gate_passed={rebuilt.gate_passed} reason={rebuilt.gate_failure_reason}'
            )
        )
