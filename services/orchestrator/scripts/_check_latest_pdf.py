import re
from collections import Counter
from pathlib import Path

from pypdf import PdfReader

pdf_path = Path(r"C:\Users\z005b8nt\Downloads\doc-001 (7).pdf")
reader = PdfReader(str(pdf_path))
text = "\n".join(page.extract_text() or "" for page in reader.pages)

has_emdash = bool(re.search(r"Figure\s+\d+\s*[—-]", text))
period_count = len(re.findall(r"Figure\s+\d+\.\s", text))
emdash_count = len(re.findall(r"Figure\s+\d+\s*[—-]", text))
appendix_count = len(re.findall(r"Appendix Figure\s+\d+", text))
layers_tables = len(re.findall(r"Layers\s+Description\s+Significance/?\s*Value", text, flags=re.IGNORECASE))

lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
long_lines = [ln.casefold() for ln in lines if len(ln) >= 80]
counts = Counter(long_lines)
repeats_sorted = sorted([(k, v) for k, v in counts.items() if v > 1], key=lambda x: -x[1])[:8]

print(f"PDF={pdf_path}")
print(f"HAS_EMDASH_CAPTION={has_emdash}")
print(f"PERIOD_CAPTION_COUNT={period_count}")
print(f"EMDASH_CAPTION_COUNT={emdash_count}")
print(f"APPENDIX_COUNT={appendix_count}")
print(f"LAYERS_TABLE_HEADER_COUNT={layers_tables}")
print("TOP_REPEATS=")
for line, n in repeats_sorted:
    print(f"x{n}: {line[:180]}")
