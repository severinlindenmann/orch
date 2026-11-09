window.BLOCK_FIXTURES = [
  {
    "name": "valid-all-ten.json",
    "doc": {
      "schema": "orch.blocks/1",
      "from": "job",
      "blocks": [
        {
          "type": "summary",
          "text": "Exported 1 204 invoices.\nTwo were skipped.",
          "tone": "good"
        },
        {
          "type": "steps",
          "items": [
            {
              "label": "Read invoices",
              "state": "done"
            },
            {
              "label": "Write CSV",
              "state": "done"
            },
            {
              "label": "Upload",
              "state": "failed",
              "note": "No network"
            }
          ]
        },
        {
          "type": "progress",
          "label": "Files",
          "done": 12,
          "total": 40,
          "unit": "files"
        },
        {
          "type": "stat",
          "label": "Rows",
          "value": 1204,
          "tone": "neutral",
          "delta": "+12 since last week"
        },
        {
          "type": "kv",
          "items": [
            {
              "key": "Month",
              "value": "November"
            },
            {
              "key": "Skipped",
              "value": 2
            }
          ]
        },
        {
          "type": "table",
          "title": "Skipped invoices",
          "columns": [
            {
              "key": "id",
              "label": "Invoice"
            },
            {
              "key": "amount",
              "label": "Amount",
              "kind": "number"
            },
            {
              "key": "why",
              "label": "Why"
            }
          ],
          "rows": [
            {
              "id": "INV-1001",
              "amount": 120.5,
              "why": "No customer"
            },
            {
              "id": "INV-1002",
              "amount": null,
              "why": "Empty"
            }
          ],
          "total_rows": 2
        },
        {
          "type": "file",
          "path": ".orch/tickets/t_inv7c2/artifacts/invoices.csv",
          "label": "invoices.csv",
          "size": 48211
        },
        {
          "type": "link",
          "url": "https://example.com/reports/11",
          "label": "Report in the browser"
        },
        {
          "type": "log",
          "title": "Last lines",
          "lines": [
            "writing row 1204",
            "done in 3.1 s"
          ],
          "cut": 1202
        },
        {
          "type": "chart",
          "kind": "bar",
          "title": "Invoices per day",
          "x_label": "Day",
          "y_label": "Invoices",
          "series": [
            {
              "name": "Invoices",
              "points": [
                [
                  "Mon",
                  210
                ],
                [
                  "Tue",
                  305
                ],
                [
                  "Wed",
                  null
                ]
              ]
            }
          ]
        }
      ],
      "title": "Invoice export"
    }
  },
  {
    "name": "valid-empty-table.json",
    "doc": {
      "schema": "orch.blocks/1",
      "from": "job",
      "blocks": [
        {
          "type": "table",
          "columns": [
            {
              "key": "a",
              "label": "A"
            }
          ],
          "rows": []
        }
      ]
    }
  },
  {
    "name": "valid-line-chart.json",
    "doc": {
      "schema": "orch.blocks/1",
      "from": "orch",
      "blocks": [
        {
          "type": "chart",
          "kind": "line",
          "series": [
            {
              "name": "Latency",
              "points": [
                [
                  1,
                  120
                ],
                [
                  2,
                  98.5
                ],
                [
                  3,
                  101
                ]
              ]
            },
            {
              "name": "Errors",
              "points": [
                [
                  1,
                  0
                ],
                [
                  2,
                  2
                ],
                [
                  3,
                  0
                ]
              ]
            }
          ]
        }
      ]
    }
  },
  {
    "name": "valid-markup-stays-text.json",
    "doc": {
      "schema": "orch.blocks/1",
      "from": "agent",
      "blocks": [
        {
          "type": "summary",
          "text": "<b>bold</b> <script>alert(1)</script>"
        },
        {
          "type": "kv",
          "items": [
            {
              "key": "<i>k</i>",
              "value": "[link](https://x.example)"
            }
          ]
        }
      ]
    }
  },
  {
    "name": "valid-picture-preview.json",
    "doc": {
      "schema": "orch.blocks/1",
      "from": "agent",
      "blocks": [
        {
          "type": "file",
          "path": "reports/chart.png",
          "label": "Chart",
          "size": 20480,
          "preview": "image"
        }
      ]
    }
  },
  {
    "name": "valid-progress-unknown-total.json",
    "doc": {
      "schema": "orch.blocks/1",
      "from": "job",
      "blocks": [
        {
          "type": "progress",
          "label": "Pages",
          "done": 7,
          "total": null
        }
      ]
    }
  },
  {
    "name": "valid-unknown-block.json",
    "doc": {
      "schema": "orch.blocks/1",
      "from": "job",
      "blocks": [
        {
          "type": "summary",
          "text": "Before"
        },
        {
          "type": "heatmap",
          "cells": [
            [
              1,
              2
            ]
          ]
        },
        {
          "type": "summary",
          "text": "After"
        }
      ]
    }
  }
];
