"""Regenerate the sample drawings in /samples.

    cd backend && ./venv/bin/python -m scripts.generate_samples
"""
from app.config import SAMPLES_DIR
from app.exporters.dxf_writer import build_dxf
from app.exporters.pdf_report import drawing_pdf
from app.samples import water_treatment


def main() -> None:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    build_dxf(water_treatment(errors=True)).saveas(SAMPLES_DIR / "water_treatment_pid.dxf")
    build_dxf(water_treatment(errors=False)).saveas(SAMPLES_DIR / "water_treatment_pid_clean.dxf")
    (SAMPLES_DIR / "water_treatment_pid.pdf").write_bytes(drawing_pdf(water_treatment(errors=True)))
    print(f"Samples written to {SAMPLES_DIR}")


if __name__ == "__main__":
    main()
