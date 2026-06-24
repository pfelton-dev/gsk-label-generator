# Sterling Label Generator v1.2

Streamlit webapp for generating MDC and Non-MDC carton labels on Avery 5163 sheets.

## Features

- Avery 5163 layout: 4" x 2", 10 labels per 8.5" x 11" sheet
- Label type selector: MDC or Non-MDC
- Centered text
- Auto-wrap and auto-shrink text
- Job # field for saving/tracking only
- Automatic individual carton labels
- Automatic partial label generation
- Partial labels marked with `_____ PARTIAL _____`
- Carton number on the bottom
- Print full job, single carton, carton range, or missing labels
- Starting label position 1-10 for partially used sheets
- Save/load jobs using JSON files

## MDC Inputs

- Job #
- GMM#
- WMN#
- Description
- Total Pieces
- Pieces Per Box

## Non-MDC Inputs

- Job #
- Destination
- Description
- Fold / Size
- Total Qty
- Qty Per Full Box
- Pack Of # Per Full Box
- Pieces Per Pack

The Non-MDC partial carton also calculates partial packs, for example:

`6 PACKS OF 6 + 1 PACK OF 4`

## Run Locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Printing

When printing the PDF, use:

- Scale: 100%
- Do not use "Fit to Page"
- Paper: Letter 8.5" x 11"
