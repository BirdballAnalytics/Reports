# BC Baseball Reports

Two report types, chosen on entry.

**Scouting** — a full sheet per arm (season line, movement plot, metrics with
VAA/EXT/RelH/InZone%, batter-hand splits, usage by situation, and an eight-panel
location grid) plus a staff sheet that folds once down the middle, ordered from
most innings to fewest. Includes the retag workspace.

Both need two files: the pitch-level export and a season pitching export.
Without the second one the sheets still build, but the season lines are blank
and the staff sheet cannot be ordered by innings.

**Hitting** — one-page hitter game reports: spray chart, swing decisions,
contact quality, plate discipline and pitch-group splits. Every printed
figure is verified against the reference one-pager.

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

## Views and conventions

Location panels are drawn in **catcher's view** — a right-handed hitter stands
on the left of each panel. TruMedia ships `x` the other way round (its
hit-by-pitches put righties at +x, and a righty stands third-base side, which
the catcher sees on his left), so `panels.py` negates it. `CATCHER_VIEW` at the
top of that file flips both the data and the home plate together, so the two
can never disagree.

Heat maps use a single-hue ramp rather than the usual blue-to-red: density is a
magnitude and has no meaningful midpoint.

RISP is reconstructed, not exported. No TruMedia column carries baserunners, so
`advanced.add_risp` walks each half-inning and applies the advancement notation
in the play description. On the reference season it produced a 27.2% RISP rate
against a typical 22-26%, with one contradiction in 229 scoring plays. It cannot
see steals or wild pitches, so treat it as close rather than exact.

## Season stats on the staff sheet

Upload a second CSV in the Scouting sidebar with columns `player`, `IP`,
`ERA`, `H`, `K`, `BB` and `InZone%` (a TruMedia season pitching export has
these already). Each card then carries that line under the pitcher's name,
and the sheet title picks up the team name automatically.

These are official counting stats and are deliberately not derived from the
pitch data. Strikeouts and walks do reconstruct exactly, but innings and hits
come up short -- untracked pitches and missing games -- and ERA is not
derivable at all, because earned versus unearned runs is an official-scorer
judgement that no pitch-level export carries.

Matching is by surname, with a first initial as tiebreaker, so `Radel`,
`Radel, Jack`, `Jack Radel` and `J. Radel` all resolve to the same pitcher.
Anyone without a stats row is named in a warning and still gets a card.

## Adding a new export format

TrackMan and TruMedia spellings are both recognised (TruMedia writes `Vel`,
`Spin`, `IndVertBrk`, `HorzBrk`). Column names live in `bc_reports/schema.py`. Add the vendor's spelling to
the alias list for whichever canonical field it maps to, and add any new
pitch names to `PITCH_ALIASES`. A file missing a required column raises a
message naming the field rather than producing empty plots.

## Hitting report definitions

- **In zone**: |side| ≤ 0.83 ft, height 1.50–3.50 ft (rulebook).
- **Heart**: |side| ≤ 0.558 ft, height 1.83–3.17 ft (Statcast attack zone).
- **Chase%**: swings at pitches outside the rulebook zone, over pitches
  outside the zone.
- **Hard hit**: exit velocity ≥ 95 mph. **Sweet spot**: launch angle 8–32°.
- The shaded box on the contact-quality chart marks 95+ mph at 10–30°. Note
  this is a different window from the sweet-spot% figure (8–32°, any exit
  velocity); change `SHADE_LA` / `SWEET_LO` / `SWEET_HI` in `hitting.py` to
  align them.
- **GB / LD / FB**: from TaggedHitType when present, otherwise launch-angle
  bands (under 10°, 10–25°, 25° and up).
- **Pitch groups**: Fastball covers four-seam, sinker and cutter; Breaking
  covers slider, curveball and sweeper; Offspeed covers changeup and
  splitter. Anything unrecognized lands in Other.

### Feedback form

Each hitter's report is followed by a Post Series Hitter Feedback page with
real fillable PDF fields, so it can be completed in any PDF reader rather
than printed. Player, date and opponent arrive pre-filled and stay editable;
opponent is taken from the team whose pitchers the hitter actually faced, so
it is right even when one export contains both clubs. Turn the page off with
the checkbox in the Hitting sidebar.

### Ballpark

The outfield wall defaults to 330 down the lines, 375 to the gaps and 403 to
straightaway center; change it in the Hitting sidebar. The wall curve is
fitted through those three distances with even powers only, so it runs
smoothly through center rather than forming a point there. Batted balls are
plotted at true bearing and distance, which means a ball clears the drawn
wall exactly when it actually cleared it.

Plate appearances are grouped by date, inning, half and PA-of-inning, with
the last pitch of each carrying the outcome. If those columns are absent the
app falls back to PitchofPA resets.

### Brand assets

`assets/wordmark.png` is the Eagles script that sits centered in the header.
`assets/conference.png` is the ACC mark in the footer. Replace either file
to change the mark; if one is missing the header falls back to the BC logo
and the footer drops to text only. `assets/Retro_on_Red.png` is the BC logo
used on the scouting reports.

## Layout

```
app.py                  Streamlit UI and mode routing
bc_reports/schema.py    column mapping for both pitching and hitting exports
bc_reports/retags.py    rules engine and persistence
bc_reports/reports.py   scouting PDFs
bc_reports/hitting.py   hitting PDFs
make_fixture.py         rebuilds the reference game for verification
assets/                 logos
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
