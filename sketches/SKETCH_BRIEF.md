# What each sketch needs to show

Draw these yourselves (paper and phone photo, tablet, or Excalidraw) and save them here as
`q1.jpg`, `q2.jpg`, `q3.jpg`, `q4.jpg`, `q5.jpg`. The report picks them up automatically.
Rough is fine. Use the real numbers from the report tables for axis ranges and labels. The grader's checklist is: title, axis labels, legend, how data maps to marks,
and the interactions, clear enough that someone else could build it.

Feedback also asked for: readable labels, the same scale when panels are compared, missing data shown
on purpose, and categories that don't rely on color alone.

## Q1: When do people ride?
- Title: "When New Yorkers ride: members vs. casual riders"
- Two heatmaps side by side, same size, same color scale: **Members** and **Casual riders**.
- x-axis: hour of day, 0 to 23 (label every 3 hours). y-axis: Mon to Sun.
- Color: share of that group's weekly trips (light = few, dark = many). One legend for both.
- Under each panel title: "about N trips per day".
- Annotate the two commute peaks (around 8:00 and 17:00) on the member panel.
- Interaction note: hover a cell shows "Wed 8:00, members: 67 trips per day".

## Q2: Where and when do stations gain or lose bikes? (main view)
- Title: "Bikes gained or lost through trips, per dock, by hour"
- Map of Manhattan, Brooklyn and Queens with each station as a small triangle.
  - Pointing down = losing bikes, pointing up = gaining (so it works without color).
  - Color: diverging, red = losing, blue = gaining, white/very light at 0.
  - Legend with units: "net trips per dock" (e.g. -1 ... 0 ... +1).
  - Grey hollow circles = "no dock data".
- Above the map: hour slider (0 to 23), and a toggle Weekday / Weekend.
- Small note on the map: "Trip flow only. Staff rebalancing is not included."
- Side panel, shown when a station is clicked: bar chart, x = hour, two bars per hour
  (departures and arrivals, solid vs. striped), plus a line for cumulative net per dock.
  Title = station name, docks.

## Q3: Where do the trips behind the imbalance come from?
- Title: "Where morning trips go"
- Real data: 70% of weekday-morning trips go to a nearby neighborhood in the same borough; only 6.5% cross
  the East River. So the map is about short hops into Midtown, and East River crossings are just a filter.
- Left: 4 × 4 borough matrix (rows = start, columns = end), each cell shaded and labeled with trips per day.
- Right: map with curved lines between neighborhood centers for the top ~30 pairs.
  - Line width = trips per day (show a width legend: 10, 50, 100).
  - East River crossings solid, others dashed (say so in the legend).
- Period selector: Weekday 7–10 / Weekday 16–19 / Other weekday / Weekend.
- Interactions: click a neighborhood to show only its flows; selecting a station in Q2 highlights its neighborhood here.

## Q4: Weather and season
- Title: "Busy days and quiet days"
- Top: calendar heatmap for the three months we use (January, July, October 2025): three small blocks,
  columns = weeks, rows = Mon–Sun, color = trips that day (sequential, one shared scale). Holidays outlined.
- Bottom: two scatter plots side by side, same y-scale: **Members** and **Casual**.
  - x-axis: high temperature (°F). y-axis: trips as % of that group's average day in that month.
  - Filled dot = rainy day, hollow dot = dry day (legend).
- Interaction: hover a day shows date, trips, temperature, rain; clicking a calendar day highlights it in the scatter.

## Q5 (optional): e-bike vs. classic
- Title: "How far do e-bike riders go?"
- x-axis: straight-line trip distance (km, 0–8). y-axis: share of trips.
- Two step histograms: e-bike solid line, classic dashed line. Short vertical tick at each median.
- Note under the axis: "straight-line distance, shorter than the real route".
