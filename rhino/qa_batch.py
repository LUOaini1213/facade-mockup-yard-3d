#! python3
"""Native Rhino batch entrypoint; copied with qa_model.py to an ASCII temp path."""
import json
import os
from pathlib import Path
import sys
import traceback

import Rhino
import scriptcontext as sc


def main():
    model_path = os.environ['MOCKUP_RHINO_QA_MODEL']
    report_path = Path(os.environ['MOCKUP_RHINO_QA_REPORT'])
    try:
        if not Rhino.RhinoDoc.OpenFile(model_path):
            raise RuntimeError('Rhino could not open the exported model')
        sc.doc = Rhino.RhinoDoc.ActiveDoc
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from qa_model import main as check_active_document
        check_active_document()
    except Exception:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps({'model': Path(model_path).name, 'passed': False,
                                          'errors': [traceback.format_exc()]}, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
