const summaryExpression = `={{ (() => {
  const batches = $json.summaries;
  if (!Array.isArray(batches)) throw new Error('Invalid summary response');
  const escape = value => String(value ?? '').replace(/[&<>"']/g, character =>
    ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'})[character]);
  const title = 'TalentForge AI — Daily Interview Selection Summary';
  const cellStyle = 'border:1px solid #cbd5e1;padding:8px 6px;text-align:left;vertical-align:top;overflow-wrap:anywhere;word-break:break-word';
  const headings = ['No.', 'Candidate Name', 'Email', 'Job Title', 'Matching Score'];
  const headers = headings.map(label =>
    '<th scope="col" style="' + cellStyle + ';background:#1e293b;color:#fff">' + label + '</th>').join('');
  const rows = batches.map(batch => {
    if (!Array.isArray(batch.recipients) || !batch.recipients.length || !Array.isArray(batch.candidates) || !batch.candidates.length)
      throw new Error('Empty summary snapshot');
    const entries = batch.candidates.map((candidate, index) =>
      '<tr>' + [index + 1, candidate.name, candidate.email, candidate.job_title, candidate.match_score]
        .map(value => '<td style="' + cellStyle + '">' + escape(value) + '</td>').join('') + '</tr>').join('');
    const html = '<div style="max-width:720px;margin:0 auto;padding:16px 8px;font-family:Arial,sans-serif;color:#172033;font-size:15px;line-height:1.5">' +
      '<h1 style="font-size:22px;line-height:1.25;margin:0 0 16px">' + title + '</h1>' +
      '<p>Dear Recruiter,</p><p>The following candidates have successfully passed automated CV screening and have been selected for interviews.</p>' +
      '<table style="width:100%;table-layout:fixed;border-collapse:collapse;font-size:13px"><colgroup>' +
      '<col style="width:9%"><col style="width:21%"><col style="width:29%"><col style="width:23%"><col style="width:18%">' +
      '</colgroup><thead><tr>' + headers + '</tr></thead><tbody>' + entries + '</tbody></table>' +
      '<p><strong>Total Selected Candidates: ' + batch.candidates.length + '</strong></p>' +
      '<p>Best regards,<br>TalentForge AI — Automated Recruitment System</p></div>';
    return Object.assign({}, batch, { subject: title, html });
  });
  return JSON.stringify({ __demo_rows: rows });
})() }}`;

export function withRecruiterSummaryHtml(workflow) {
  const updated = structuredClone(workflow);
  const mapping = updated.nodes.find(node => node.name === 'Map Prepare Organization Messages');
  const smtp = updated.nodes.find(node => node.name === 'Recruiter SMTP');
  if (mapping?.type !== 'n8n-nodes-base.set' || smtp?.type !== 'n8n-nodes-base.emailSend') {
    throw new Error('Expected the local-demo recruiter summary nodes');
  }
  mapping.parameters.jsonOutput = summaryExpression;
  smtp.parameters.emailFormat = 'html';
  smtp.parameters.html = '={{ $json.html }}';
  delete smtp.parameters.text;
  smtp.parameters.options = { ...smtp.parameters.options, appendAttribution: false };
  return updated;
}
