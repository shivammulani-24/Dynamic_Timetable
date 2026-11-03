# Group 86: Dynamic Timetable Monitoring System (Mini Project report + poster)

| File | What it is |
|---|---|
| `86_Dynamic_Timetable_Monitoring_System.tex` | Main LaTeX file, laid out exactly as the department template (`synopsis.tex`); compile this |
| `86_Dynamic_Timetable_Monitoring_System.pdf` | Compiled report |
| `details.tex` | Names, UIDs, guide, HOD (edit here; updates every page) |
| `frontmatter/` | Title page, approval certificate, declaration, abstract (template order) |
| `chapters/s1…s8` | Template sections: 1 Introduction, 2 Literature Survey (15 papers), 3 Analysis, 4 Design and Methodology, 5 Results and Discussion, 6 Conclusion and Further Work, 7 Research Paper/Poster, 8 Plagiarism Report |
| `parts/` | Diagrams, algorithms and tables used by the sections |
| `references.tex` | IEEE-style references |
| `figures/` | SPIT logo, real-PDF page, app screenshots, the IEEE paper and A3 poster PDFs included in Section 7. Put `plagiarism-report.pdf` and `ai-detection-report.pdf` here and follow the note at the top of `chapters/s8-plagiarism.tex` |
| `poster/86_Dynamic_Timetable_Poster.pptx` | A3 poster on the department template (editable in PowerPoint) |
| `poster/86_Dynamic_Timetable_Poster_A3.pdf` | Poster exported at A3 size |
| `poster/src/` | Poster diagrams (TikZ), screenshots strip, QR code, build script |

**Build:** Overleaf → *Upload Project* (zip of this folder) → compiler *pdfLaTeX* → Recompile. Locally:
`latexmk -pdf 86_Dynamic_Timetable_Monitoring_System.tex`, or run `pdflatex` three times.
Step-by-step instructions are in `docs/13-ese-demo-guide.md`, Part E.
