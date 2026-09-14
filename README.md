# Bullpen Reports

Upload TrackMan or TruMedia CSVs, correct mis-tagged pitches, download the
individual scouting reports and the foldable staff sheet.

The PDF output is verified pixel-identical to the reports built by hand —
all 16 pages match exactly.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Opens at http://localhost:8501.

## Deploy so other coaches can reach it

**Streamlit Community Cloud** (free, simplest):

1. Push this folder to a GitHub repo (private is fine).
2. At share.streamlit.io, point a new app at the repo and `app.py`.
3. In the app's **Settings → Secrets**, add:
   ```toml
   APP_PASSWORD = "pick-something"
   ```

Anything else that runs a container works too (Render, Railway, Fly). Start
command: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`.

**Set a password.** Roster data on a public URL is otherwise readable by
anyone with the link. With `APP_PASSWORD` unset the app runs open, which is
fine locally and not fine hosted.

## Corrections

Two kinds, both saved per pitcher so they survive re-uploads:

- **Rules** — "Fronio: cutters with IVB below −10 become curveballs." These
  re-apply automatically to every future bullpen.
- **Hand picks** — lasso or box-select points on the movement plot and
  reassign just those pitches. Hand picks always win over rules.

Either can also drop pitches outright (`— drop —`), which is how the stray
splitter came out of DeLue's arsenal.

### Persistence warning

Corrections save to `data/retags.json`. **Most hosts wipe the filesystem on
redeploy and on idle restarts** — Streamlit Cloud does. Use the sidebar's
*Download corrections* button after a working session and *Restore
corrections* to load the file back. For permanent storage, swap the two
functions at the top of `app.py` (`load_book` / `save_book`) for S3, a
database, or a file committed to the repo.

## Profiles

Each pitcher is labeled Stock, North/South, or East/West from the ratio of
his arsenal's vertical spread to its horizontal spread, counting only pitch
types with 3 or more reps.

The default cutoffs (0.75 / 1.10) were fit to one specific staff whose
median ratio was 0.87. Horizontal separation naturally runs wider than
vertical, so a neutral arsenal sits *below* 1.0, not at it. **Re-center
cutoffs on this staff** is on by default and rescales both cutoffs to the
uploaded group's median — leave it on unless you want fixed thresholds
across rosters.

## Adding a new export format

Column names live in `bc_reports/schema.py`. Add the vendor's spelling to
the alias list for whichever canonical field it maps to, and add any new
pitch names to `PITCH_ALIASES`. A file missing a required column raises a
message naming the field rather than producing empty plots.

## Layout

```
app.py                  Streamlit UI
bc_reports/schema.py    column mapping, pitch-name folding, untracked filter
bc_reports/retags.py    rules engine and persistence
bc_reports/reports.py   both PDF builders
assets/                 BC logo
```

`reports.py` has no Streamlit dependency — it takes a DataFrame and returns
PDF bytes, so it can also run from a script or a cron job.

## Notes on the data

- Pitches with no velocity or break reading are excluded and counted on the
  Review tab. In the reference dataset these were all tagged "Knuckleball,"
  which is what the unit records when it fails to track a pitch.
- Tags of Undefined, Other, and Unknown are treated the same way.
- Duplicate pitch IDs across files are dropped, so re-uploading an
  overlapping export is safe.
