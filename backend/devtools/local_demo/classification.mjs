import fs from "node:fs";
export function professionalEvidence(lines) {
  // Keep these patterns ASCII in generated expressions across shell and JSON exports.
  const labeled = /^(?:skills|technologies|tools|education|qualification[s]?|projects?|experience|volunteering|certifications?)\s*[:\u2013\u2014-]\s*\S/i;
  const activity = /^(?:[-*\u2013\u2014\u2022\u25aa\u25cf\u25e6]\s*)?(?:built|developed|implemented|designed|maintained|managed|led|created|operated|supported|taught|organized|volunteered|completed|earned|studied|worked|tested|repaired|trained|coordinated|delivered)\s+\S+\s+\S/i;
  const role = /\b(?:engineer|developer|technician|analyst|teacher|assistant|coordinator|apprentice|student|volunteer|designer|operator|specialist)\s*(?:at|@|[-\u2013\u2014|])\s*\S/i;
  const sectionHeading = /^(?:(?:technical|core|academic|personal|professional|work) )?(?:skills|education|experience|projects|certifications|qualifications|interests|summary)\s*[:\u2013\u2014-]?$/i;
  const nonCandidateHeading = /^(?:(?:(?:professional|personal|academic) )?(?:references?|referees?)|job (?:description|requirements)|(?:required|desired|preferred) skills|requirements)\s*(?::.*|[\u2013\u2014-])?$/i;
  const skillHeading = /^(?:(?:technical|core|professional|computer) skills|skills(?: (?:&|and) (?:expertise|competencies|technologies))?|technical (?:proficiency|competencies|expertise|toolkit)|programming languages|languages|(?:project )?(?:tech|technology) stack|technologies|tools|databases?|frameworks(?: (?:&|and) (?:tools|libraries))?|libraries)\s*[:\u2013\u2014-]?$/i;
  const qualification = /\b(?:no|not|never|without|aspiring|interested|unfamiliar|beginner|required|optional|seeking)\b/i;
  const bullet = /^(?:[-*\u2013\u2014]\s+|[\u2022\u25aa\u25cf\u25e6]\s*)/;
  const experienceHeading = /^(?:(?:professional|work) )?experience\s*[:\u2013\u2014-]?$/i;
  const describedRole = /\b(?:engineer|developer|technician|analyst|teacher|assistant|coordinator|apprentice|volunteer|designer|operator|specialist)\b/i;
  const workActivity = /\b(?:built|developed|implemented|designed|maintained|managed|led|created|operated|supported|tested|worked)\b/i;
  let experienceStart = -1;
  let skillStart = -1;
  let excluded = false;
  return lines.filter((line, index) => {
    const body = line.text.replace(bullet, '');
    if (nonCandidateHeading.test(body)) {
      experienceStart = -1;
      skillStart = -1;
      excluded = true;
      return false;
    }
    if (sectionHeading.test(body) && !skillHeading.test(body)) {
      experienceStart = experienceHeading.test(body) ? index : -1;
      skillStart = -1;
      excluded = false;
    }
    if (excluded) return false;
    if (skillHeading.test(body)) {
      experienceStart = -1;
      skillStart = index;
      return false;
    }
    const cells = body.split(/[,;|]/).map(cell => cell.trim());
    const tableLabel = cells.length >= 2 && body.includes('|') && skillHeading.test(cells[0]);
    const skills = tableLabel ? cells.slice(1) : cells;
    const list = (tableLabel || (skillStart >= 0 && index - skillStart <= 32 && skills.length >= 2))
      && skills.length <= 20 && !qualification.test(body)
      && skills.every(cell => /^[\w+#][\w.+#/& -]{0,59}$/.test(cell) && cell.split(/\s+/).length <= 5);
    if (!list && skillStart >= 0) skillStart = -1;
    const contextualRole = experienceStart >= 0 && index > experienceStart
      && index - experienceStart <= 32
      && describedRole.test(line.text) && workActivity.test(line.text);
    return list || labeled.test(line.text) || activity.test(line.text) || role.test(line.text) || contextualRole;
  });
}
export function validateModelClassification(output, pre) {
  const failure = [{json:{failure_code:'workflow_classification_failed'}}];
  if (!pre || pre.override || !Array.isArray(pre.evidence_lines) || typeof output !== 'string') return failure;
  let result;
  try { result = JSON.parse(output); } catch { return failure; }
  if (!result || Object.keys(result).sort().join(',') !== 'category,evidence,reason,spam_suspected'
    || !['clean','spam','suspicious','meaningless'].includes(result.category)
    || result.spam_suspected !== (result.category !== 'clean')
    || typeof result.reason !== 'string' || !result.reason.trim()
    || !Array.isArray(result.evidence) || result.evidence.length < 1
    || result.evidence.length > Math.max(32, pre.evidence_lines.length)
    || !result.evidence.every(id => Number.isInteger(id) && id >= 0 && id < pre.evidence_lines.length)) return failure;
  const cleanEvidence = professionalEvidence(pre.evidence_lines);
  if (result.category === 'clean' && cleanEvidence.length === 0) return failure;
  if (result.evidence.length > 32) {
    // Recover only a clean answer with a verified primary citation. Every ID
    // must be valid and distinct, and none of the extra IDs are forwarded.
    const primary = cleanEvidence.find(line => line.id === result.evidence[0]);
    if (result.category !== 'clean' || !primary
      || new Set(result.evidence).size !== result.evidence.length) return failure;
    return [{json:{classification:'clean',evidence:[primary.text]}}];
  }
  const cited = result.category === 'clean' ? cleanEvidence.slice(0,2) : result.evidence.map(id => pre.evidence_lines[id]);
  return [{json:{classification:result.category,evidence:cited.map(line => line.text)}}];
}
export function correctClassification(workflow) {
  const w=structuredClone(workflow);
  if(w.nodes.some(n=>n.name==="Map Validate Classification")) return w;
  const pre=w.nodes.find(n=>n.name==="Security Pre-Check");
  const validator=w.nodes.find(n=>n.name==="Validate Classification");
  const classify=w.nodes.find(n=>n.name==="Classify CV");
  if (validator.parameters.jsCode.includes("return validateModelClassification($json.output,")) return w;
  const helper=professionalEvidence.toString()+"\n";
  if(!pre.parameters.jsCode.includes("professional_evidence_ids")){
    pre.parameters.jsCode=helper+pre.parameters.jsCode.replace("...b, evidence_lines,", "...b, evidence_lines, professional_evidence_ids:professionalEvidence(evidence_lines).map(line=>line.id),");
  }
  validator.parameters.jsCode=helper+validateModelClassification.toString()+
    "\nreturn validateModelClassification($json.output, $('Security Pre-Check').item.json);";
  classify.parameters.text="={{ JSON.stringify({untrusted_cv_lines:$json.evidence_lines,professional_evidence_ids:$json.professional_evidence_ids}) }}";
  classify.parameters.options.systemMessage = classify.parameters.options.systemMessage.replace(
    'evidence contains one or two integer IDs from the supplied lines.',
    'evidence is an array containing exactly one integer ID from the supplied lines.',
  );
  classify.parameters.options.systemMessage += "\nprofessional_evidence_ids is a deterministic source index. For clean, prefer IDs from that index. Names and contact details alone are not professional evidence. Output no extra fields. The validator independently reconstructs clean evidence from the original source and never accepts model-authored evidence text.";
  classify.parameters.options.systemMessage += "\nReturn exactly one integer in evidence. For clean, use the strongest ID from professional_evidence_ids. Never enumerate the CV lines.";
  return w;
}
if(process.argv[2]){
 const w=JSON.parse(fs.readFileSync(process.argv[2],"utf8").replace(/^\uFEFF/,""));
 fs.writeFileSync(process.argv[3],JSON.stringify(correctClassification(w),null,2)+"\n");
}
