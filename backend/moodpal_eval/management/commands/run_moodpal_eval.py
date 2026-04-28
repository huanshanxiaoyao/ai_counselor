from django.core.management.base import BaseCommand, CommandError

from backend.moodpal_eval.services.run_executor import execute_run
from backend.moodpal_eval.services.run_service import get_run


class Command(BaseCommand):
    help = 'Execute a MoodPal eval run by run id.'

    def add_arguments(self, parser):
        parser.add_argument('--run-id', required=True, help='MoodPalEvalRun UUID.')

    def handle(self, *args, **options):
        run_id = options['run_id']
        try:
            run = get_run(run_id)
        except Exception as exc:
            raise CommandError(f'run not found: {run_id}') from exc

        final_run = execute_run(str(run.id))
        self.stdout.write(
            self.style.SUCCESS(
                f'run={final_run.id} status={final_run.status} gate_passed={final_run.gate_passed} reason={final_run.gate_failure_reason}'
            )
        )
