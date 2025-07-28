from APIs import get_pdf_outline
import json
from pathlib import Path

INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")
INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def main():
    for pdf_file in INPUT_DIR.glob("*.pdf"):
        print(f"Processing: {pdf_file.name}")
        result = get_pdf_outline(pdf_file.name)
        json_filename = OUTPUT_DIR / f"{pdf_file.stem}.json"
        with open(json_filename, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"Saved: {json_filename}")
        
if __name__ == "__main__":
    main()