import fs from "node:fs";
export function professionalEvidence(lines) {
  const labeled = /^(?:skills|technologies|tools|education|qualification[s]?|projects?|experience|volunteering|certifications?)\s*:\s*\S/i;
  const activity = /^(?:[-*•]\s*)?(?:built|developed|implemented|designed|maintained|managed|led|created|operated|supported|taught|organized|volunteered|completed|earned|studied|worked|tested|repaired|trained|coordinated|delivered)\s+\S+\s+\S/i;
  const role = /\b(?:engineer|developer|technician|analyst|teacher|assistant|coordinator|apprentice|student|volunteer|designer|operator|specialist)\s*(?:at|@|[-–—|])\s*\S/i;
  const sectionHeading = /^(?:(?:technical|professional|work) )?(?:skills|education|experience|projects|certifications|qualifications|references|interests|summary)\s*[:–—-]?$/i;
  const experienceHeading = /^(?:(?:professional|work) )?experience\s*[:–—-]?$/i;
  const describedRole = /\b(?:engineer|developer|technician|analyst|teacher|assistant|coordinator|apprentice|volunteer|designer|operator|specialist)\b/i;
  const workActivity = /\b(?:built|developed|implemented|designed|maintained|managed|led|created|operated|supported|tested|worked)\b/i;
  let experienceStart = -1;
  return lines.filter((line, index) => {
    if (sectionHeading.test(line.text)) {
      experienceStart = experienceHeading.test(line.text) ? index : -1;
    }
    const contextualRole = experienceStart >= 0 && index > experienceStart
      && index - experienceStart <= 32
      && describedRole.test(line.text) && workActivity.test(line.text);
    return labeled.test(line.text) || activity.test(line.text) || role.test(line.text) || contextualRole;
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
    || !Array.isArray(result.evidence) || result.evidence.length < 1 || result.evidence.length > 32
    || !result.evidence.every(id => Number.isInteger(id) && id >= 0 && id < pre.evidence_lines.length)) return failure;
  const cleanEvidence = professionalEvidence(pre.evidence_lines);
  if (result.category === 'clean' && cleanEvidence.length === 0) return failure;
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
  classify.parameters.options.systemMessage += "\nprofessional_evidence_ids is a deterministic source index. For clean, prefer IDs from that index. Names and contact details alone are not professional evidence. Output no extra fields. The validator independently reconstructs clean evidence from the original source and never accepts model-authored evidence text.";
  classify.parameters.options.systemMessage += "\nReturn only 1 to 3 of the strongest source evidence IDs. Do not enumerate the CV lines.";
  return w;
}
if(process.argv[2]){
 const w=JSON.parse(fs.readFileSync(process.argv[2],"utf8").replace(/^\uFEFF/,""));
 fs.writeFileSync(process.argv[3],JSON.stringify(correctClassification(w),null,2)+"\n");
}
