const DATA_ROOT = "../data/processed";
const DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const HOUR_LABELS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, "0"));

async function loadCsv(file) {
  const response = await fetch(`${DATA_ROOT}/${file}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Could not load ${file}: ${response.status}`);
  }
  return d3.csvParse(await response.text(), (d) => {
    const out = {};
    Object.keys(d).forEach((key) => {
      const raw = d[key];
      out[key] = raw === "" || raw === "NA" ? null : raw;
    });
    return out;
  });
}

function addAxis(svg, xScale, yScale, height, margin, xLabel, yLabel) {
  svg.append("g")
    .attr("class", "axis")
    .attr("transform", `translate(0,${height - margin.bottom})`)
    .call(d3.axisBottom(xScale).tickValues(xScale.domain()))
    .call((g) => g.selectAll("text").attr("transform", "translate(0,8)"));

  svg.append("g")
    .attr("class", "axis")
    .attr("transform", `translate(${margin.left},0)`)
    .call(d3.axisLeft(yScale));

  svg.append("text")
    .attr("class", "axis-label")
    .attr("x", margin.left + (width - margin.left - margin.right) / 2)
    .attr("y", height - 12)
    .attr("text-anchor", "middle")
    .text(xLabel);

  svg.append("text")
    .attr("class", "axis-label")
    .attr("transform", "rotate(-90)")
    .attr("x", -(margin.top + (height - margin.top - margin.bottom) / 2))
    .attr("y", 16)
    .attr("text-anchor", "middle")
    .text(yLabel);
}

function renderQ1(data) {
  const chart = document.getElementById("q1-chart");
  chart.innerHTML = "";

  const width = 980;
  const height = 330;
  const margin = { top: 20, right: 20, bottom: 52, left: 68 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;

  const svg = d3.select(chart).append("svg")
    .attr("viewBox", `0 0 ${width} ${height}`);

  const groups = ["member", "casual"];
  const innerWidth = plotWidth / groups.length;

  groups.forEach((group, idx) => {
    const bucket = data.filter((d) => d.rider_type === group);
    const x = d3.scaleLinear().domain([0, 23]).range([margin.left + idx * innerWidth, margin.left + (idx + 1) * innerWidth - 10]);
    const y = d3.scaleBand().domain(DAY_ORDER).range([margin.top, height - margin.bottom]).padding(0.04);
    const color = d3.scaleSequential()
      .domain([d3.min(bucket, (d) => +d.trips_per_day), d3.max(bucket, (d) => +d.trips_per_day)])
      .interpolator(d3.interpolateYlGnBu);

    const g = svg.append("g");

    g.append("text")
      .attr("x", margin.left + idx * innerWidth + innerWidth / 2)
      .attr("y", margin.top - 4)
      .attr("text-anchor", "middle")
      .style("font-size", "12px")
      .style("font-weight", "600")
      .text(group.charAt(0).toUpperCase() + group.slice(1));

    g.selectAll("rect")
      .data(bucket)
      .join("rect")
      .attr("x", (d) => x(+d.hour))
      .attr("y", (d) => y(d.day_name))
      .attr("width", Math.max(1, x(1) - x(0) - 2))
      .attr("height", y.bandwidth())
      .attr("fill", (d) => color(+d.trips_per_day));

    g.append("g")
      .attr("class", "axis")
      .attr("transform", `translate(${margin.left + idx * innerWidth},0)`)
      .call(d3.axisLeft(y));

    g.append("g")
      .attr("class", "axis")
      .attr("transform", `translate(0,${height - margin.bottom})`)
      .call(d3.axisBottom(x).ticks(6).tickFormat((d) => `${String(d).padStart(2, "0")}:00`));

    g.append("text")
      .attr("x", margin.left + idx * innerWidth + innerWidth / 2)
      .attr("y", height - 16)
      .attr("text-anchor", "middle")
      .attr("class", "axis-label")
      .text("Hour of day");
  });

  svg.append("text")
    .attr("x", margin.left + (plotWidth / 2) - 10)
    .attr("y", height - 16)
    .attr("text-anchor", "middle")
    .attr("class", "axis-label")
    .text("Hour of day");

  svg.append("text")
    .attr("transform", "rotate(-90)")
    .attr("x", -((height) / 2))
    .attr("y", 18)
    .attr("text-anchor", "middle")
    .attr("class", "axis-label")
    .text("Day of week");

  const legend = svg.append("g").attr("transform", `translate(${margin.left + plotWidth - 180}, ${margin.top})`);
  const legendScale = d3.scaleLinear().domain([0, 1]).range([0, 120]);
  const legendColor = d3.scaleSequential().domain([0, 1]).interpolator(d3.interpolateYlGnBu);

  legend.selectAll("rect")
    .data(d3.range(0, 1.01, 0.2))
    .join("rect")
    .attr("x", (d, i) => i * 24)
    .attr("y", 0)
    .attr("width", 24)
    .attr("height", 10)
    .attr("fill", (d) => legendColor(d));

  legend.append("text")
    .attr("x", 0)
    .attr("y", -4)
    .attr("class", "label")
    .text("Trips per day");
}

function renderQ2(data, dayType, hour) {
  const chart = document.getElementById("q2-chart");
  chart.innerHTML = "";

  const width = 980;
  const height = 380;
  const margin = { top: 20, right: 16, bottom: 48, left: 160 };

  const filtered = data.filter((d) => d.day_type === dayType && Number(d.hour) === Number(hour));
  const sorted = filtered
    .map((d) => ({ ...d, net_per_dock: Number(d.net_per_dock) }))
    .sort((a, b) => Math.abs(b.net_per_dock) - Math.abs(a.net_per_dock))
    .slice(0, 20);

  const xMin = Math.min(0, d3.min(sorted, (d) => d.net_per_dock) || 0);
  const xMax = Math.max(0, d3.max(sorted, (d) => d.net_per_dock) || 0);
  const x = d3.scaleLinear().domain([xMin, xMax]).range([margin.left, width - margin.right]);
  const y = d3.scaleBand().domain(sorted.map((d) => d.station_id)).range([margin.top, height - margin.bottom]).padding(0.2);

  const svg = d3.select(chart).append("svg").attr("viewBox", `0 0 ${width} ${height}`);

  const zeroLine = x(0);
  svg.append("line")
    .attr("x1", zeroLine)
    .attr("x2", zeroLine)
    .attr("y1", margin.top)
    .attr("y2", height - margin.bottom)
    .attr("stroke", "#4a5568")
    .attr("stroke-dasharray", "4 4");

  svg.append("g")
    .attr("class", "axis")
    .attr("transform", `translate(0,${height - margin.bottom})`)
    .call(d3.axisBottom(x).ticks(8));

  svg.append("g")
    .attr("class", "axis")
    .attr("transform", `translate(${margin.left},0)`)
    .call(d3.axisLeft(y));

  svg.selectAll("rect")
    .data(sorted)
    .join("rect")
    .attr("x", (d) => Math.min(x(0), x(d.net_per_dock)))
    .attr("y", (d) => y(d.station_id))
    .attr("width", (d) => Math.abs(x(d.net_per_dock) - x(0)))
    .attr("height", y.bandwidth())
    .attr("fill", (d) => d.net_per_dock >= 0 ? "#2b6cb0" : "#c0392b")
    .attr("opacity", 0.9)
    .append("title")
    .text((d) => `${d.station_id}: ${Number(d.net_per_dock).toFixed(3)} net per dock`);

  svg.append("text")
    .attr("x", width / 2)
    .attr("y", height - 8)
    .attr("text-anchor", "middle")
    .attr("class", "axis-label")
    .text("Net trips per dock");

  svg.append("text")
    .attr("x", -height / 2)
    .attr("y", 16)
    .attr("transform", "rotate(-90)")
    .attr("text-anchor", "middle")
    .attr("class", "axis-label")
    .text("Station");
}

function renderQ3(data, period) {
  const chart = document.getElementById("q3-chart");
  chart.innerHTML = "";

  const width = 980;
  const height = 420;
  const margin = { top: 20, right: 24, bottom: 32, left: 280 };

  const filtered = data
    .filter((d) => d.period === period)
    .sort((a, b) => b.trips - a.trips)
    .slice(0, 12)
    .map((d) => ({
      label: `${d.start_nta_name} → ${d.end_nta_name}`,
      trips: Number(d.trips),
      crosses: d.crosses_borough === "true" || d.crosses_borough === true,
    }));

  const x = d3.scaleLinear().domain([0, d3.max(filtered, (d) => d.trips) || 1]).range([margin.left, width - margin.right]);
  const y = d3.scaleBand().domain(filtered.map((d) => d.label)).range([margin.top, height - margin.bottom]).padding(0.25);

  const svg = d3.select(chart).append("svg").attr("viewBox", `0 0 ${width} ${height}`);

  svg.append("g")
    .attr("class", "axis")
    .attr("transform", `translate(0,${height - margin.bottom})`)
    .call(d3.axisBottom(x).ticks(6));

  svg.append("g")
    .attr("class", "axis")
    .attr("transform", `translate(${margin.left},0)`)
    .call(d3.axisLeft(y));

  svg.selectAll("rect")
    .data(filtered)
    .join("rect")
    .attr("x", margin.left)
    .attr("y", (d) => y(d.label))
    .attr("width", (d) => x(d.trips) - margin.left)
    .attr("height", y.bandwidth())
    .attr("fill", (d) => d.crosses ? "#d97706" : "#2b6cb0")
    .attr("opacity", 0.88)
    .append("title")
    .text((d) => `${d.label}: ${d.trips.toLocaleString()} trips`);

  svg.append("text")
    .attr("x", width / 2)
    .attr("y", height - 8)
    .attr("text-anchor", "middle")
    .attr("class", "axis-label")
    .text("Trips per day");
}

function renderQ4(data) {
  const chart = document.getElementById("q4-chart");
  chart.innerHTML = "";

  const width = 980;
  const height = 380;
  const margin = { top: 24, right: 30, bottom: 52, left: 64 };

  const monthlyMemberAvg = d3.rollup(
    data,
    (v) => d3.mean(v, (d) => Number(d.member_trips)),
    (d) => d.date.slice(0, 7)
  );

  const monthlyCasualAvg = d3.rollup(
    data,
    (v) => d3.mean(v, (d) => Number(d.casual_trips)),
    (d) => d.date.slice(0, 7)
  );

  const rows = data.map((d) => ({
    date: d.date,
    month: d.date.slice(0, 7),
    tmax_f: Number(d.tmax_f),
    member_pct: (Number(d.member_trips) / (monthlyMemberAvg.get(d.date.slice(0, 7)) || 1)) * 100,
    casual_pct: (Number(d.casual_trips) / (monthlyCasualAvg.get(d.date.slice(0, 7)) || 1)) * 100,
    rainy: Number(d.precip_in) > 0 || Number(d.snow_in) > 0,
  }));

  const x = d3.scaleLinear().domain([0, d3.max(rows, (d) => d.tmax_f) || 100]).range([margin.left, width - margin.right]);
  const y = d3.scaleLinear().domain([0, d3.max(rows, (d) => Math.max(d.member_pct, d.casual_pct)) || 200]).range([height - margin.bottom, margin.top]);

  const svg = d3.select(chart).append("svg").attr("viewBox", `0 0 ${width} ${height}`);

  svg.append("g")
    .attr("class", "grid")
    .attr("transform", `translate(${margin.left},0)`)
    .call(d3.axisLeft(y).ticks(6).tickSize(-(width - margin.left - margin.right)).tickFormat(""));

  svg.append("g")
    .attr("class", "axis")
    .attr("transform", `translate(0,${height - margin.bottom})`)
    .call(d3.axisBottom(x).ticks(8));

  svg.append("g")
    .attr("class", "axis")
    .attr("transform", `translate(${margin.left},0)`)
    .call(d3.axisLeft(y).ticks(6));

  svg.selectAll("circle.member")
    .data(rows)
    .join("circle")
    .attr("class", "member")
    .attr("cx", (d) => x(d.tmax_f))
    .attr("cy", (d) => y(d.member_pct))
    .attr("r", 4)
    .attr("fill", "#2b6cb0")
    .attr("fill-opacity", (d) => d.rainy ? 1 : 0.7)
    .append("title")
    .text((d) => `${d.date}: member = ${d.member_pct.toFixed(1)}% of monthly average`);

  svg.selectAll("circle.casual")
    .data(rows)
    .join("circle")
    .attr("class", "casual")
    .attr("cx", (d) => x(d.tmax_f))
    .attr("cy", (d) => y(d.casual_pct))
    .attr("r", 4)
    .attr("fill", "#d97706")
    .attr("fill-opacity", (d) => d.rainy ? 1 : 0.7)
    .append("title")
    .text((d) => `${d.date}: casual = ${d.casual_pct.toFixed(1)}% of monthly average`);

  svg.append("text")
    .attr("x", width / 2)
    .attr("y", height - 8)
    .attr("text-anchor", "middle")
    .attr("class", "axis-label")
    .text("Daily high temperature (°F)");

  svg.append("text")
    .attr("x", -height / 2)
    .attr("y", 18)
    .attr("transform", "rotate(-90)")
    .attr("text-anchor", "middle")
    .attr("class", "axis-label")
    .text("Trips as % of that month’s average day");

  const legend = svg.append("g").attr("transform", `translate(${width - 210}, ${margin.top})`);
  legend.append("circle").attr("cx", 0).attr("cy", 0).attr("r", 5).attr("fill", "#2b6cb0");
  legend.append("text").attr("x", 12).attr("y", 5).attr("class", "label").text("Members");
  legend.append("circle").attr("cx", 0).attr("cy", 20).attr("r", 5).attr("fill", "#d97706");
  legend.append("text").attr("x", 12).attr("y", 25).attr("class", "label").text("Casual riders");
}

function renderQ5(data) {
  const chart = document.getElementById("q5-chart");
  chart.innerHTML = "";

  const width = 980;
  const height = 340;
  const margin = { top: 20, right: 20, bottom: 42, left: 56 };

  const grouped = d3.groups(data, (d) => d.rideable_type);
  const x = d3.scaleLinear().domain([0, 8]).range([margin.left, width - margin.right]);
  const y = d3.scaleLinear().range([height - margin.bottom, margin.top]);
  const svg = d3.select(chart).append("svg").attr("viewBox", `0 0 ${width} ${height}`);

  grouped.forEach(([bikeType, rows]) => {
    const totals = rows.map((d) => ({
      bin: Number(d.dist_bin_km),
      trips: Number(d.trips),
    }));
    const max = d3.max(totals, (d) => d.trips) || 1;
    y.domain([0, max]);

    svg.append("path")
      .datum(totals)
      .attr("fill", "none")
      .attr("stroke", bikeType === "classic_bike" ? "#2b6cb0" : "#d97706")
      .attr("stroke-width", 2)
      .attr("d", d3.line()
        .x((d) => x(d.bin))
        .y((d) => y(d.trips))
        .curve(d3.curveStepAfter));

    svg.append("g")
      .attr("class", "axis")
      .attr("transform", `translate(0,${height - margin.bottom})`)
      .call(d3.axisBottom(x).ticks(9).tickFormat((d) => `${d.toFixed(1)} km`));

    svg.append("g")
      .attr("class", "axis")
      .attr("transform", `translate(${margin.left},0)`)
      .call(d3.axisLeft(y).ticks(6));
  });

  svg.append("text")
    .attr("x", width / 2)
    .attr("y", height - 8)
    .attr("text-anchor", "middle")
    .attr("class", "axis-label")
    .text("Straight-line trip distance (km)");

  svg.append("text")
    .attr("x", -height / 2)
    .attr("y", 18)
    .attr("transform", "rotate(-90)")
    .attr("text-anchor", "middle")
    .attr("class", "axis-label")
    .text("Trips");

  const legend = svg.append("g").attr("transform", `translate(${width - 220}, ${margin.top})`);
  legend.append("line").attr("x1", 0).attr("x2", 30).attr("y1", 0).attr("y2", 0).attr("stroke", "#2b6cb0").attr("stroke-width", 2);
  legend.append("text").attr("x", 38).attr("y", 4).attr("class", "label").text("Classic bike");
  legend.append("line").attr("x1", 0).attr("x2", 30).attr("y1", 22).attr("y2", 22).attr("stroke", "#d97706").attr("stroke-width", 2);
  legend.append("text").attr("x", 38).attr("y", 26).attr("class", "label").text("E-bike");
}

async function main() {
  try {
    const [hourly, stationHour, daily, od, hist] = await Promise.all([
      loadCsv("hourly_profile.csv"),
      loadCsv("station_hour.csv"),
      loadCsv("daily.csv"),
      loadCsv("od_nta.csv"),
      loadCsv("distance_hist.csv"),
    ]);

    renderQ1(hourly);

    const q2Day = document.getElementById("q2-day-type");
    const q2Hour = document.getElementById("q2-hour");
    const q2HourLabel = document.getElementById("q2-hour-label");

    function updateQ2() {
      q2HourLabel.textContent = `${String(q2Hour.value).padStart(2, "0")}:00`;
      renderQ2(stationHour, q2Day.value, q2Hour.value);
    }

    q2Day.addEventListener("change", updateQ2);
    q2Hour.addEventListener("input", updateQ2);
    updateQ2();

    const q3Period = document.getElementById("q3-period");
    q3Period.addEventListener("change", () => renderQ3(od, q3Period.value));
    renderQ3(od, q3Period.value);

    renderQ4(daily);
    renderQ5(hist);
  } catch (error) {
    console.error(error);
    document.body.insertAdjacentHTML(
      "beforeend",
      `<div style="padding:24px;color:#b91c1c;">Error loading data: ${error.message}</div>`
    );
  }
}

document.addEventListener("DOMContentLoaded", main);
