# Waiting-room announcement clips

The TV board (`/opd/display/`) speaks each newly-called token by playing a short
MP3 per symbol, in sequence — e.g. token `A-042` plays `A.mp3`, `0.mp3`, `4.mp3`,
`2.mp3`. Because token symbols are a small finite set, these are **pre-generated
server-side** rather than synthesized in the browser (browser TTS silently fails
on cheap offline Android sticks — see PLAN §4).

## Enable
Set `OPD_ANNOUNCE_AUDIO=1` (and optionally `OPD_ANNOUNCE_LANG=mr|hi|en`). Until
the clips exist the board falls back to a chime automatically, so enabling this
without the files is harmless.

## Generate
List exactly which files are needed for the current doctors/languages:

```
python manage.py announcement_clips
```

Then create one short MP3 per symbol per language at
`static/announce/<lang>/<SYMBOL>.mp3` (e.g. `static/announce/mr/A.mp3`), using
any offline TTS or recorded voice, and run `collectstatic`.
