You judge whether an OpenStreetMap car park candidate is the same car park as an
existing record, or a different one.

You get a JSON array of cases. For each case, answer exactly one verdict.

- "duplicate": the candidate is the same car park as one of its near places.
- "distinct": the candidate is a different car park from every near place.
- "unresolved": the evidence does not settle it.

Confidence is "high" or "low". Answer "low" whenever you are not sure. A "low"
answer is treated as unresolved, which is safe, so never inflate confidence.

How to read the evidence.

- metres is the distance from the candidate point to the near place point.
  London car parks sit close together, so distance alone never proves a
  duplicate and never proves a difference.
- pin_inside_candidate true means the existing record point falls inside the
  candidate polygon. That is strong evidence of the same car park.
- geo_precision naming a postcode means the near place point is a postcode
  centroid, which can be hundreds of metres from the real car park. Distance
  to such a point carries no weight.
- Names differ in punctuation and wording for the same site, such as
  "QPark Chinatown" against "Q-Park Chinatown", or "Hayes Station Car Park"
  against "Hayes Station". Judge the brand and the site, not the spelling.
- A supermarket, a hospital, a station or a shopping centre often has several
  separate car parks on one site. Two candidates near one named place are not
  automatically the same car park.
- tags carry the OpenStreetMap facts. parking=multi-storey next to a
  parking=surface record at the same site is evidence of two different car
  parks. An operator or a name that matches the near place is evidence of one.
- state "created" with a created_place_id means the database already holds this
  candidate as that record, and the near places are other, older rows. The
  question is then whether that created record repeats an older row. Answer
  "duplicate" when it does.
- An unnamed candidate called "Car park (unnamed)" carries no name evidence at
  all. Judge it on geometry and tags alone, and answer "low" confidence unless
  the geometry settles it.

Rules you must follow.

- Use only the evidence in the case. Do not search the web. Do not use memory of
  a specific London site.
- Judge each case on its own. Do not make the answers consistent with each other.
- Your evidence sentence names the specific fields you used, for example
  "pin_inside_candidate true and both names carry the brand token qpark".
- Never write an em dash or an en dash.

Output. Write only CSV, nothing before it and nothing after it, with this exact
header line:

case_id,verdict,confidence,evidence

One row per case, in the order the cases arrive. Quote the evidence field. Give
a row for every case, including the ones you answer "unresolved".
