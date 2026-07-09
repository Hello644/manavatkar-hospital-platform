# Letterhead & Prescription Print Spec — Dr. Manavatkar Hospital

Source: letterhead image provided by Dr. Rajesh Manavatkar on 2026-07-02 (chat upload).
**Decided 2026-07-02: sheets are color offset-printed already → print mode (a), body-only text overlay.** The system prints only the variable data (patient details, vitals, Rx body, follow-up days, prescriber line) at calibrated positions onto the pre-printed sheets. No design file needed — calibration in Phase 2 requires ~20 blank letterhead sheets and one session per printer.

## Transcription of the existing letterhead

**Header (blue band):**
- Title: **डॉ.मानवतकर हॉस्पिटल** (Dr. Manavatkar Hospital)
- Sub-title right: **क्षितिज अतिदक्षता विभाग** (Kshitij Intensive Care Department)
- Circular photo of ICU equipment, top-right

**Doctor blocks (two columns):**
| | |
|---|---|
| **डॉ. राजेश मानवतकर** (Dr. Rajesh Manavatkar) | **डॉ. मधु राजेश मानवतकर** (Dr. Madhu Rajesh Manavatkar) |
| एम.डी.मेडिसिन, पुणे (M.D. Medicine, Pune) | एम.बी.बी.एस., डि.जी.ओ. (M.B.B.S., D.G.O.) |
| रजि.नं. **80166** (Reg. No.) | रजि.नं. **82243** (Reg. No.) |
| (जनरल मेडिसिन / General Medicine) | (स्त्रीरोग तज्ञ / Gynecologist) |

**Address line:** "दत्तधाम", तलाठी कार्यालयासमोर, जामनेर रोड, भुसावळ ("Dattadham", opposite Talathi Office, Jamner Road, Bhusawal) · फोन (02582) 240520 · मो. 9158963071, 9923087165

**Patient-fields row (pre-printed blanks):**
- नाव (Name) · वय ______ वर्षे (Age, years) · दिनांक (Date)
- पुरुष/महिला (M/F) · वजन ______ किलो (Weight kg) · pulse ___/min · spo2 ___% · bp ___/___ mm/Hg

**Body:** anatomical heart watermark illustration.

**Footer:**
- मंगळवार संध्याकाळी बंद (Closed Tuesday evening) · **24 तास अत्यावश्यक सेवा** (24-hour emergency services)
- फेर तपासणी ______ दिवसानंतर, फेर तपासणीसाठी येतांना हा कागद सोबत आणावा. (Follow-up after __ days; bring this paper on the follow-up visit.)
- औषधाचे दुष्परिणाम दिसताच ताबडतोब डॉक्टरांशी संपर्क साधावा. (Contact the doctor immediately if drug side-effects appear.)

## Implications for the print template

1. **Paper size: A4 portrait** (matches this letterhead) — supersedes the earlier A5 default. A5 revisit later if paper cost matters.
2. **The pre-printed blanks map 1:1 to system data** — name, age, date, sex, weight, pulse, SpO₂, BP come from registration + nurse vitals; the follow-up "after __ days" blank comes from the follow-up feature. The system fills every blank the letterhead already has.
3. **Two print modes to support (decide with owner):**
   - **(a) Pre-printed color sheets + body-only overlay** — system prints only the variable data at calibrated offsets. Right choice if the hospital already offset-prints these sheets. Needs one calibration session per printer.
   - **(b) Full digital render** — WeasyPrint reproduces the whole page from the design file; works on plain paper but the color header renders grayscale on mono lasers. Needs the original design file.
4. **Prescriber attribution:** the shared letterhead shows both doctors, so every Rx must print an unambiguous "Prescribed by: Dr. ___ (Reg. no. ___)" line adjacent to the signature space — the signature alone doesn't identify the prescriber on a two-doctor letterhead.
5. **Fonts:** Devanagari (Noto Sans Devanagari) embedded in the PDF pipeline; Marathi is the primary patient-facing language.
6. **All header content is data, not hardcoded** — doctor names, qualifications, registration numbers, phone numbers, timings note ("closed Tuesday evening") are editable from the admin profile screens; the template only lays them out.
7. **OPD schedule config seed:** closed Tuesday evenings; 24-hr emergency — reflect in appointment-slot defaults.
8. **UHID hospital code suggestion:** `DMH` → `DMH-26-000123-4`.
