import { loadSavedReports, renderReportCollection } from "./reporting.js";

const reportOutput = document.querySelector("#report-output");
const reportEmpty = document.querySelector("#report-empty");

function renderPage() {
  const reports = loadSavedReports();
  const hasReports = renderReportCollection(reports, reportOutput);
  reportEmpty.hidden = hasReports;
}

renderPage();
