# Bedrock Guardrail for /api/agent: AWS checks what visitors send and what the model says, apart
# from the model itself. The daily token limit caps cost; this caps content. Prompt attacks
# (jailbreaks, prompt injection) are blocked on input. Content filters are LOW for sexual,
# violent, and misconduct content because medical concept names and questions use those words
# ("Sexual dysfunction", "Assault", "Suicidal ideation"); hate and insults are MEDIUM. One denied
# topic: advice about a person's own care, which the system prompt also refuses.
# A version freezes the settings the app uses; changing them means a new version.

resource "aws_bedrock_guardrail" "agent" {
  name        = "${local.name}-agent"
  description = "RWE Workbench /api/agent: prompt attacks, harmful content, clinical advice"

  blocked_input_messaging   = "I can't help with that. This is a research demonstration on synthetic data; I can answer questions about counts of conditions, drugs, and measurements, the trial emulation results, and data quality."
  blocked_outputs_messaging = "I can't share that. This is a research demonstration on synthetic data; I can answer questions about counts of conditions, drugs, and measurements, the trial emulation results, and data quality."

  content_policy_config {
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
    }
    filters_config {
      type            = "HATE"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
    filters_config {
      type            = "INSULTS"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
    filters_config {
      type            = "SEXUAL"
      input_strength  = "LOW"
      output_strength = "LOW"
    }
    filters_config {
      type            = "VIOLENCE"
      input_strength  = "LOW"
      output_strength = "LOW"
    }
    filters_config {
      type            = "MISCONDUCT"
      input_strength  = "LOW"
      output_strength = "LOW"
    }
  }

  topic_policy_config {
    topics_config {
      name       = "personal_clinical_advice"
      type       = "DENY"
      definition = "Advice to a person about their own or a patient's diagnosis, treatment, medication, or dose. Not counts, study results, or statistics from research data."
      examples = [
        "What dose of metformin should I take?",
        "Should my patient stop warfarin before surgery?",
        "Do I have diabetes if my HbA1c is 7.2?",
        "Which blood pressure drug should I start?",
      ]
    }
  }
}

resource "aws_bedrock_guardrail_version" "agent" {
  guardrail_arn = aws_bedrock_guardrail.agent.guardrail_arn
  description   = "Initial settings, 2026-11-21"

  # Any change to the guardrail publishes a new version and the task moves to it. Old versions
  # stay in AWS (skip_destroy), so a task still running the old one keeps working until ECS
  # replaces it.
  skip_destroy = true

  lifecycle {
    create_before_destroy = true
    replace_triggered_by  = [terraform_data.guardrail_updated]
  }
}

# The guardrail's last update time, kept apart from the guardrail. A targeted apply of the
# guardrail alone (the DRAFT check in the runbook) leaves this behind, so the next full apply
# still sees the change and publishes a version.
resource "terraform_data" "guardrail_updated" {
  input = aws_bedrock_guardrail.agent.updated_at
}
