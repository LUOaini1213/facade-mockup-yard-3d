"""Run the saved-model QA in native Rhino 8 on Windows, in a hidden bounded process."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, default=ROOT / 'model' / 'vmu_site_future.3dm')
    parser.add_argument('--report', type=Path, default=ROOT / 'model' / 'vmu_site_future_rhino_qa.json')
    parser.add_argument('--timeout', type=int, default=240)
    parser.add_argument('--enrich', action='store_true', help='Bind public PBR assets, views, images and geometry QA')
    parser.add_argument('--probe-render', action='store_true', help='Inspect native rendered-mode settings')
    parser.add_argument('--delivery-only', action='store_true', help='Verify the saved native delivery without rebuilding or changing it')
    parser.add_argument('--rhino', type=Path,
                        default=Path(os.environ.get('RHINO_EXE', r'C:\Program Files\Rhino 8\System\Rhino.exe')))
    args = parser.parse_args()
    if (args.enrich or args.delivery_only) and args.report == ROOT / 'model' / 'vmu_site_future_rhino_qa.json':
        args.report=ROOT / 'model' / 'vmu_site_future_rhino_delivery.json'
    if args.probe_render:
        args.report=ROOT/'model'/'vmu_site_future_render_probe.json'
    if os.name != 'nt':
        parser.error('Native Rhino batch QA requires Windows')
    if not args.rhino.is_file() or not args.model.is_file():
        parser.error('Rhino executable or exported model is missing')
    if args.timeout <= 0:
        parser.error('--timeout must be a positive number of seconds')
    model_path, report_path = args.model.resolve(), args.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if report_path.exists():
        report_path.unlink()  # Reject stale success reports from a previous run.
    with tempfile.TemporaryDirectory(prefix='mockup_rhino_qa_') as temporary:
        temp_path = Path(temporary)
        script = temp_path / ('qa_delivery.py' if args.delivery_only else 'probe_render.py' if args.probe_render else 'enrich_model.py' if args.enrich else 'qa_batch.py')
        if not str(script).isascii() or ' ' in str(script):
            parser.error('TMP/TEMP must point to an ASCII directory without spaces')
        for filename in ('qa_batch.py', 'qa_model.py', 'enrich_model.py','probe_render.py','qa_delivery.py'):
            shutil.copyfile(ROOT / 'rhino' / filename, temp_path / filename)
        environment = dict(os.environ, MOCKUP_RHINO_ROOT=str(ROOT), MOCKUP_RHINO_QA_MODEL=str(model_path),
                           MOCKUP_RHINO_QA_REPORT=str(report_path))
        # The entire Rhino command macro needs one outer pair of quotes; the
        # copied script path has no spaces and needs no nested quotes.
        command = '"%s" /nosplash /notemplate /runscript="_-RunPythonScript %s _-Exit _No"' % (args.rhino, script)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        process = subprocess.Popen(command, env=environment, startupinfo=startup)
        print('Native Rhino PID: '+str(process.pid),flush=True)
        try:
            process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise SystemExit('Rhino QA timed out; only this launched process was terminated')
    if not report_path.is_file():
        raise SystemExit('Rhino did not write a QA report; check its licence and Python script environment')
    result = json.loads(report_path.read_text(encoding='utf-8'))
    print(json.dumps({key: value for key, value in result.items() if key != 'components'},
                     ensure_ascii=False, indent=2))
    print('Report: ' + str(report_path))
    raise SystemExit(0 if result.get('passed') or args.probe_render and 'error' not in result else 1)


if __name__ == '__main__':
    main()
