# BC Baseball Reports

Two report types, chosen on entry.

**Scouting** — a full sheet per arm (season line, movement plot, metrics with
VAA/EXT/RelH/InZone%, batter-hand splits, usage by situation, and an eight-panel
location grid) plus a staff sheet that folds once down the middle, ordered from
most innings to fewest. Includes the retag workspace.

Feed it the pitch-level export. A season pitching export is optional: supply
one and those official numbers are printed, leave it out and the whole stat
line is rebuilt from the pitch data instead.

**Hitting** — a two-page weekly report per hitter. Page one is the charts:
spray, swing decisions, contact quality, plate discipline and a full-width
pitch-group table carrying both the swing-decision rates and the results
(AVG / SLG / OPS / Barrel% / H / XBH). Page two is the fillable form: his
plate-appearance log, a coach feedback box and the development plan.

The header covers whatever range the data spans, not a single date, and
lists every opponent that hitter faced in it -- worked out from his own rows,
so a file holding both clubs' hitters does not put every team above every
batter.

Form fields on the feedback page carry no length limit. ReportLab defaults
every text field to `maxlen=100`, which writes `/MaxLen 100` into the PDF;
viewers then show a character counter beside the box and stop accepting input
at a hundred characters -- about two sentences, in a box meant to hold a
week of feedback. All three field types pass `maxlen=NO_LIMIT` so the key is
omitted entirely.

A one-hitter download saves as `Surname-YYYY-MM-DD.pdf` — `Mainolfi-2026-09-29.pdf`
— dated by the day it was pulled rather than the day of the games, since a
weekly report spans several. Several hitters at once save as
`Hitting-3-hitters-2026-09-29.pdf`.

Rate stats in the pitch-group table are charged to the group of the pitch
that *ended* the plate appearance, the usual convention for a "vs fastballs"
split. Barrel% uses Statcast's window: 98 mph and 26-30 degrees at the
opening, widening to 8-50 at 116. It does not widen evenly, so the published
steps are anchored in `BARREL_ANCHORS` and interpolated between rather than
drawn as one straight line, which runs a degree or two tight through the
middle.

## Upload size

`.streamlit/config.toml` sets `maxUploadSize = 2048`, so the uploader accepts
files up to 2 GB instead of Streamlit's 200 MB default.

**That file lives in a hidden folder, and GitHub's drag-and-drop upload skips
hidden folders.** If the deployed app still says "200MB per file", that is
why. Create it by hand instead: **Add file -> Create new file**, type
`.streamlit/config.toml` as the name — typing the slash makes the folder —
then paste the contents in.

The real ceiling on a hosted app is memory, not this number. To buy headroom,
both loaders read the header first and then re-read keeping only the columns
the reports map: a TrackMan export carries about two hundred columns and the
reports use twenty-six. On a 200 MB file that is 108 MB in memory instead of
344 MB. Output is unchanged — the normalised frames and the rendered sheets
are identical either way.

Rough timings on one core: 76,000 pitches load in about a second, and the
base-state walk behind RISP takes about forty. That walk is a per-appearance
Python loop, so it scales with pitches, not file size — a genuinely large
season will spend a few minutes there before any PDF is drawn.

Duplicate pitch IDs are dropped when files are combined, so overlapping
exports can be uploaded together without double-counting.

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

## Where the stat line comes from

Upload a season stats CSV and those numbers are used as they are — they are
the official book. Upload nothing and the whole line is rebuilt from the
pitch file instead, so the sheets never print a row of dashes.

Checked against a full season of Notre Dame pitching, deriving from the pitch
file alone reproduced the official export closely:

| Field | Result |
| --- | --- |
| Strikeouts, walks | exact, all 16 pitchers |
| Innings pitched | exact for 15 of 16; 449.7 of 450.0 across the staff |
| InZone% | within 0.2 points on average, 0.6 at worst |
| Hits | within 1.4 on average (scorer's hit-or-error calls differ) |
| ERA | within 0.2–0.6 for everyone over 18 innings |

Innings are the interesting one. Counting outs from plate-appearance
outcomes alone misses every out made on the bases — caught stealing,
pickoffs, runners thrown out — and comes up about 5% short over a season.
So innings are reconstructed by differencing the outs count across each
half-inning instead, which recovers all of them.

Two things the derived line cannot know:

- **Earned versus unearned.** ERA is really runs per nine. Runs are read
  from the RBI notation when the file has play descriptions, which tracks
  earned runs more closely than a raw score would — a run that scores on an
  error carries no RBI — and each run is charged to the pitcher who put that
  runner on rather than the one on the mound when he scored. Without that
  last step a reliever who inherits a jam can read several runs high.
- **Games it never saw.** Only tracked outings count, so a pitcher whose
  starts were not all recorded will show fewer innings than the book.

FIP uses `(13·HR + 3·(BB + HBP) − 2·K)/IP + 3.180`. That constant was solved
against a season of TruMedia game logs rather than borrowed from the major
leagues: at 3.180 it reproduces TruMedia's own published FIP to within 0.006
across all 60 games, and every residual lands on a whole number of
hit-by-pitches. The usual major-league 3.10 misses by half a run.

## Plate locations, TrackMan and TruMedia

The two vendors do not measure the same thing. TrackMan (and Statcast)
report feet — side from the middle of the plate, height from the ground, so
a belt-high pitch reads about 2.5. TruMedia normalises to the strike zone
and centres it on zero, so the same pitch reads about 0.

Everything downstream works in the normalised space, so a file in feet is
rescaled on load using a 9.95-inch half-plate (8.5in of plate plus a ball's
radius) and a 1.5–3.5ft zone. Which space a file is in is decided from the
height values rather than the column name, so an export from a vendor this
app has not seen still lands in the right branch: a height measured from the
ground clusters around two and a half feet, one normalised to the zone
around nothing. When a file is rescaled the app says so in the notes above
the tabs.

Sign conventions already agree — in both vendors' exports a right-handed
hitter stands at positive x, confirmed from hit-by-pitch locations — so the
catcher's-view flip happens once, at draw time, in `panels.CATCHER_VIEW`.

## What the panels and tables show

On the staff sheet every pitch type a man throws gets a row in his metrics
table, up to six -- which covers every arsenal seen so far. The table used to
drop anything under five pitches or 2% of the arsenal and cap the card at
four rows, which quietly cost real pitches: one starter's 85 curveballs, and
one reliever's whole table. A six-row card uses a slightly tighter row so the
usage block still clears the bottom edge.

Under the metrics table on an individual sheet sits **NOTES BY PITCH** — one
write-in line for each pitch that particular man throws, colour-dotted to
match the table above it, so a two-pitch reliever gets two lines rather than
six empty ones. The RHH / LHH notes at the foot of the page are unchanged.

Because that block grows with the arsenal, the location panels below it size
themselves to the room that is left instead of assuming a fixed height. A
six-pitch sheet gives up a few points of heat map; nothing runs off the page.

The usage block on an individual sheet is split by batter hand first and
situation second -- vs LHH (Overall / 2K / RISP), then vs RHH -- so the
two-strike and scoring-position mixes can be read against the right hitter
rather than averaged across both. A slice with nothing in it says "no
pitches" rather than drawing an empty bar. The staff card keeps its compact
two-row version; six rows would not fit on a card.

The notes lines carry two writing spaces each: the approach up to two strikes
on the left, the two-strike approach after the 2K label halfway across.

Heat maps have no minimum sample. A group with one pitch in it draws that
one pitch; a group he does not throw draws an empty zone.

## Two shapes of stats file

Both are uploaded in the same slot, and **several files at a time are fine** —
the split exports come one per pitcher, so scouting a staff means uploading a
stack of them. Each file is reported as it loads, a file that will not parse
is skipped rather than stopping the rest, and a pitcher who appears in two
files keeps whichever was uploaded first. The app works out which shape each
file has.

**One row per pitcher** — the usual season export, with a `player` column.

**One row per batter hand** — a single pitcher's season split into a Lefty
row and a Righty row. This one names nobody at all: it identifies the man by
`playerId` only. The two rows are folded into one season line, and folded
properly rather than added up:

- innings sum in thirds, not as decimals (6.2 + 0.2 is 7.1)
- G and GS repeat the season total on every row, so they are taken once
- ERA is rebuilt from earned runs, recovered from each row's ERA and IP
- FIP is innings-weighted, which is exact — FIP is a rate per inning, so the
  weighted mean is the number the formula itself would give
- K% and BB% are rebuilt over batters faced, which falls out of each rate
  and its count
- InZone% is weighted by batters faced, the nearest thing to a pitch count
  the file carries

Matching a stats row to a pitcher goes by `playerId` against the pitch file's
`pitcherId` first, and by surname next. An id survives nicknames, accents and
two men sharing a surname.

A split export has neither, so there is a third fallback: the **file name**.
TruMedia exports these as `M. Bradshaw - Scouting Sheet 2.csv`, and the name
in front of the dash is read as the pitcher's when nothing inside the file
names him. That is what lets a stack of per-pitcher split files be told apart
even when their ids belong to a different vendor than the pitch file. Rename
one and it will not match, so leave the exported names alone.

Failing all three, when both files hold exactly one pitcher they are paired
anyway, since there is only one thing they can be.

## Names on the sheets

TrackMan writes `DeLue, Asher`, so the whole name is already in the pitch
file and only needs turning around. TruMedia does not: its `pitcher` column
is the bare surname, and its `fullName` column holds the *team*, not the
player. So the sheets take the best name available, in this order:

1. `playerFullName` from the season stats export — "Jack Radel"
2. `pitcherAbbrevName` from the TruMedia pitch file — "J. Radel"
3. the surname on its own

Which is one more reason to upload the season stats file alongside a TruMedia
export: without it there is no first name anywhere in the data.

## Choosing who appears

The **Download** tab opens with *Pitchers on the reports* — every arm found
in the uploaded files, most innings first, each showing his hand, season
innings and tracked pitch count. Everyone is included by default; remove a
name and he is left off both the individual sheets and the staff sheet.
*Select all* and *Clear* reset the list.

Two things the picker deliberately does not do:

- **It does not change the profile cutoffs.** Stock / North-South /
  East-West are still fit to the whole upload, so a pitcher's label cannot
  shift depending on who else you happened to print.
- **It does not silently drop new arms.** Add another CSV and any pitcher
  who was not in the data before is selected automatically; names that are
  no longer in the data fall off the list.

The caption underneath says how many pages you are about to get. The staff
sheet holds 20 cards per page, so any roster of 20 or fewer stays on the
single foldable sheet.

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
