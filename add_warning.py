#!/usr/bin/env python3
"""Ajoute un sous-titre d'avertissement au début d'un fichier SRT."""
import sys
import pysubs2

def add_warning(srt_path, gap_seconds, gap_formatted):
    subs = pysubs2.load(srt_path, encoding='utf-8')
    
    msg = (
        "⚠ SOUS-TITRE POTENTIELLEMENT DÉSYNCHRONISÉ\\N"
        f"Écart estimé : {gap_formatted}\\N"
        "Le sous-titre peut ne pas correspondre à cette version vidéo."
    )
    
    warning = pysubs2.SSAEvent(start=0, end=8000, text=msg)
    subs.insert(0, warning)
    subs.save(srt_path)
    return True

if __name__ == '__main__':
    if len(sys.argv) < 4:
        print("Usage: add_warning.py <file.srt> <gap_seconds> <gap_formatted>")
        sys.exit(1)
    
    add_warning(sys.argv[1], float(sys.argv[2]), sys.argv[3])
