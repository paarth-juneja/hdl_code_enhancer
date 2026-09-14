# What to send

## Preferred submission

Send the entire `FINAL_SUBMISSION_NEBULA_2026-09-14` folder as one ZIP file.
Do not send `.env`, `.venv`, the workspace `runs/` directories, or API keys.

If the portal accepts only separate files, upload these in order:

1. `01_REPORT/Nebula_Technical_Report.pdf`
2. `02_PRESENTATION/Nebula_Final_Presentation.pdf`
3. `02_PRESENTATION/Nebula_Final_Presentation.pptx`
4. `05_SOURCE/nebula-source-040eb0d.tar.gz`
5. `04_PROOFS/Nebula_Proof_Bundle.zip`
6. `README_FIRST.md`

## Ready-to-send message

Subject: Nebula - final submission - RTL optimization using Generative AI

Hello,

Please find our final Nebula submission attached. The package includes the
technical report, editable presentation, complete source snapshot, original and
optimized RTL, constraints, exact patch, formal-equivalence proof, matched
physical-design reports, model interaction records, test results, and checksums.

Headline verified result: on the five-master-clock ethmac5 benchmark, the
accepted cycle-exact equivalent RTL improves routed setup WNS by 0.094790 ns
(22.019%), improves TNS by 3.4968 ns (15.790%), removes 100 standard cells,
reduces cell area by 142 um^2, and reduces matched vectorless power by 0.88%.
Both physical runs finish with zero route DRC and zero antenna violations.

We explicitly do not claim timing closure: candidate setup WNS and hold WNS
remain negative. The report documents these limitations and the reproducibility
identities.

Regards,
Nebula team

## Before clicking submit

- Add team member names, institution, phone number, and registration ID wherever
  the portal requires them. Those details were not present in the repository.
- Check the organiser's portal for file-size and naming rules. The supplied brief
  does not state them.
- Keep the editable PPTX for the presentation day; use the PDF for predictable
  rendering.
- Verify the ZIP against `SHA256SUMS.txt` after uploading if the portal permits a
  download check.

