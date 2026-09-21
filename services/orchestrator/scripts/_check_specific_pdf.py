import re
import sys
from collections import Counter
from pathlib import Path

from pypdf import PdfReader

if len(sys.argv) != 2:
    print("Usage: python _check_specific_pdf.py <pdf_path>")
    raise SystemExit(2)

pdf_path = Path(sys.argv[1])
reader = PdfReader(str(pdf_path))
text = "\n".join(page.extract_text() or "" for page in reader.pages)

has_emdash = bool(re.search(r"Figure\s+\d+\s*[—-]", text))
period_count = len(re.findall(r"Figure\s+\d+\.\s", text))
emdash_count = len(re.findall(r"Figure\s+\d+\s*[—-]", text))
appendix_count = len(re.findall(r"Appendix Figure\s+\d+", text))
appendix_numbers = [int(x) for x in re.findall(r"Appendix Figure\s+(\d+)", text)]
appendix_unique = len(set(appendix_numbers))
appendix_max = max(appendix_numbers) if appendix_numbers else 0
overflow_note_present = (
    "supporting screenshot(s) are held in the source material and are not reproduced here." in text
)
layers_tables = len(re.findall(r"Layers\s+Description\s+Significance/?\s*Value", text, flags=re.IGNORECASE))

lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
long_lines = [ln.casefold() for ln in lines if len(ln) >= 80]
counts = Counter(long_lines)
repeats_sorted = sorted([(k, v) for k, v in counts.items() if v > 1], key=lambda x: -x[1])[:5]

print(f"PDF={pdf_path}")
print(f"HAS_EMDASH_CAPTION={has_emdash}")
print(f"PERIOD_CAPTION_COUNT={period_count}")
print(f"EMDASH_CAPTION_COUNT={emdash_count}")
print(f"APPENDIX_COUNT={appendix_count}")
print(f"APPENDIX_UNIQUE_NUMBERS={appendix_unique}")
print(f"APPENDIX_MAX_NUMBER={appendix_max}")
print(f"OVERFLOW_NOTE_PRESENT={overflow_note_present}")
print(f"LAYERS_TABLE_HEADER_COUNT={layers_tables}")
sample_caption_lines = []
for raw in text.splitlines():
    line = raw.strip()
    if re.match(r"^Figure\s+\d+", line):
        sample_caption_lines.append(line)
    if len(sample_caption_lines) >= 20:
        break
print("SAMPLE_CAPTION_LINES=")
for line in sample_caption_lines:
    print(line)
print("TOP_REPEATS=")
for line, n in repeats_sorted:
    print(f"x{n}: {line[:180]}")
