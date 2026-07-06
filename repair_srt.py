#!/usr/bin/env python3
"""Répare un fichier SRT mal formé en le rechargeant/sauvegardant avec pysubs2."""
import sys
import pysubs2

def repair(input_path, output_path=None):
    if output_path is None:
        output_path = input_path
    try:
        subs = pysubs2.load(input_path, encoding='utf-8')
        subs.save(output_path)
        return True
    except Exception as e:
        # Try with different encodings
        for enc in ['latin-1', 'cp1252', 'iso-8859-1']:
            try:
                subs = pysubs2.load(input_path, encoding=enc)
                subs.save(output_path)
                return True
            except Exception:
                continue
        print(f"ERROR: Cannot repair {input_path}: {e}", file=sys.stderr)
        return False

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: repair_srt.py <file.srt> [output.srt]")
        sys.exit(1)
    ok = repair(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    sys.exit(0 if ok else 1)
