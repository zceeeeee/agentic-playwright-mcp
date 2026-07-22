import { useMemo, useState } from "react";
import { Check, ChevronRight, PencilLine, ShieldAlert, Square, X } from "lucide-react";
import { useAgentStore } from "../stores/agentStore";
import type { ConfirmationOption, ConfirmationRequest } from "../types";
import { getEnterKeyAction } from "../utils/keyboard";

export function ConfirmationCard({ confirmation }: { confirmation: ConfirmationRequest }) {
  const approve = useAgentStore((state) => state.approveConfirmation);
  const reject = useAgentStore((state) => state.rejectConfirmation);
  const cancelTask = useAgentStore((state) => state.cancelCurrentTask);
  const [inputValue, setInputValue] = useState("");
  const [comment, setComment] = useState("");
  const [checkedValues, setCheckedValues] = useState<Record<string, string[]>>({});
  const [submitting, setSubmitting] = useState(false);
  const [requiredCancelArmed, setRequiredCancelArmed] = useState(false);
  const pending = confirmation.status === "pending";
  const hasDefaultValue = confirmation.default_value !== null
    && confirmation.default_value !== undefined
    && confirmation.default_value !== "";
  const options = useMemo(
    () => confirmation.options || confirmation.actions?.filter((action) => action.id.startsWith("option_")) || [],
    [confirmation.actions, confirmation.options]
  );
  const checkboxGroups = useMemo(
    () => (confirmation.fields || []).filter((field) => {
      const type = String(field.type || "").toLowerCase();
      return type === "checkbox_group" || type === "checkbox-group" || type === "multiselect";
    }),
    [confirmation.fields]
  );

  function withCheckedRequirements(value: string) {
    const requirements = checkboxGroups.flatMap((field) => {
      const name = String(field.name || field.label || "options");
      return checkedValues[name] || [];
    });
    const base = value.trim();
    if (!requirements.length) return base;
    return `${base}${base ? "\n" : ""}附加要求：${requirements.join("；")}`;
  }

  function toggleCheckedValue(fieldName: string, value: string) {
    setCheckedValues((current) => {
      const selected = current[fieldName] || [];
      return {
        ...current,
        [fieldName]: selected.includes(value)
          ? selected.filter((item) => item !== value)
          : [...selected, value],
      };
    });
  }

  async function choose(option: ConfirmationOption) {
    if (!pending || submitting) return;
    setSubmitting(true);
    try {
      await approve(confirmation.confirmation_id, option.value ?? option.label, option.id);
    } finally {
      setSubmitting(false);
    }
  }

  async function submitInput(actionId = "submit") {
    if (!pending || submitting) return;
    if (confirmation.input_required && !inputValue.trim()) {
      setRequiredCancelArmed(true);
      return;
    }
    setSubmitting(true);
    try {
      await approve(
        confirmation.confirmation_id,
        withCheckedRequirements(inputValue),
        actionId,
        comment
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function useDefaultOrCancelTask() {
    if (!pending || submitting) return;
    if (hasDefaultValue) {
      setSubmitting(true);
      try {
        await approve(
          confirmation.confirmation_id,
          withCheckedRequirements(
            confirmation.default_value ?? confirmation.current_value ?? ""
          ),
          confirmation.prompt_type === "confirm_value" ? "keep" : "default"
        );
      } finally {
        setSubmitting(false);
      }
      return;
    }
    if (confirmation.input_required) {
      if (!requiredCancelArmed) {
        setRequiredCancelArmed(true);
        return;
      }
      setSubmitting(true);
      try {
        await cancelTask(confirmation.task_id);
      } finally {
        setSubmitting(false);
      }
      return;
    }

    setSubmitting(true);
    try {
      if (confirmation.prompt_type === "confirm_value") {
        await approve(confirmation.confirmation_id, "", "keep");
      } else {
        await approve(
          confirmation.confirmation_id,
          confirmation.default_value ?? confirmation.current_value ?? "",
          "default"
        );
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function keepCurrent() {
    if (!pending || submitting) return;
    setSubmitting(true);
    try {
      await approve(confirmation.confirmation_id, "", "keep");
    } finally {
      setSubmitting(false);
    }
  }

  async function resolveGeneric(approved: boolean) {
    if (!pending || submitting) return;
    setSubmitting(true);
    try {
      if (approved) await approve(confirmation.confirmation_id, "yes", "approve", comment);
      else await reject(confirmation.confirmation_id, comment);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className={`confirmation-card prompt-${confirmation.prompt_type}`} aria-label={confirmation.title}>
      <div className="confirmation-heading">
        <ShieldAlert size={18} aria-hidden="true" />
        <div>
          <strong>{confirmation.title}</strong>
          <span>{confirmation.prompt_type === "choice" ? "请选择一个选项" : confirmation.risk_level === "high" ? "高风险操作" : "等待您的输入"}</span>
        </div>
      </div>

      {confirmation.skill_name || confirmation.parameter_name ? (
        <div className="prompt-context">
          {confirmation.skill_name ? <span>技能：{confirmation.skill_name}</span> : null}
          {confirmation.parameter_name ? <span>参数：{confirmation.parameter_name}</span> : null}
        </div>
      ) : null}

      <p>{confirmation.message}</p>

      {confirmation.current_value ? (
        <div className="current-value">
          <span>当前值</span>
          <pre>{confirmation.current_value}</pre>
        </div>
      ) : null}

      {pending && confirmation.prompt_type === "choice" ? (
        <div className="choice-list">
          {options.map((option) => (
            <button key={option.id} disabled={submitting} onClick={() => void choose(option)}>
              <span><strong>{option.label}</strong>{option.description ? <small>{option.description}</small> : null}</span>
              <ChevronRight size={17} aria-hidden="true" />
            </button>
          ))}
        </div>
      ) : null}

      {pending && (confirmation.prompt_type === "input" || confirmation.prompt_type === "confirm_value") ? (
        <div className="prompt-input">
          {hasDefaultValue ? (
            <div className="input-choice-row">
              <button className="button-secondary default-value-button" disabled={submitting} onClick={() => void useDefaultOrCancelTask()}>
                <Check size={16} />{confirmation.default_label || `使用默认值 ${confirmation.default_value}`}
              </button>
            </div>
          ) : null}
          {checkboxGroups.map((field) => {
            const fieldName = String(field.name || field.label || "options");
            const fieldOptions = Array.isArray(field.options) ? field.options : [];
            return (
              <fieldset className="prompt-checkbox-group" key={fieldName}>
                <legend>{String(field.label || "可选附加要求")}</legend>
                <div className="prompt-checkbox-options">
                  {fieldOptions.map((rawOption, index) => {
                    const option = typeof rawOption === "object" && rawOption !== null
                      ? rawOption as Record<string, unknown>
                      : { label: String(rawOption), value: String(rawOption) };
                    const label = String(option.label || option.value || "");
                    const value = String(option.value || option.label || "");
                    const checked = (checkedValues[fieldName] || []).includes(value);
                    return (
                      <label key={`${fieldName}-${index}`}>
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={submitting}
                          onChange={() => toggleCheckedValue(fieldName, value)}
                        />
                        <span>{label}</span>
                      </label>
                    );
                  })}
                </div>
              </fieldset>
            );
          })}
          <label htmlFor={`prompt-${confirmation.confirmation_id}`}>
            {confirmation.input_label || "输入内容"}
            <span className={requiredCancelArmed ? "required-indicator required-alert" : "required-indicator"}>
              {confirmation.input_required ? "（必填）" : "（可选）"}
            </span>
          </label>
          <textarea
            id={`prompt-${confirmation.confirmation_id}`}
            value={inputValue}
            onChange={(event) => {
              setInputValue(event.target.value);
              if (event.target.value.trim()) setRequiredCancelArmed(false);
            }}
            onKeyDown={(event) => {
              const action = getEnterKeyAction(event.key, event.ctrlKey, event.nativeEvent.isComposing);
              if (action === "submit") {
                event.preventDefault();
                void submitInput(confirmation.prompt_type === "confirm_value" ? "replace" : "submit");
              }
            }}
            placeholder={confirmation.input_placeholder || "请输入内容"}
            disabled={submitting}
            rows={confirmation.parameter_name?.includes("内容") ? 5 : 2}
            autoFocus
          />
          <div className="confirmation-actions">
            {confirmation.prompt_type === "confirm_value" && !hasDefaultValue ? (
              <button className="button-secondary" disabled={submitting} onClick={() => void keepCurrent()}>
                <Check size={16} />沿用当前值
              </button>
            ) : null}
            <button className="button-primary" disabled={submitting || !inputValue.trim()} onClick={() => void submitInput(confirmation.prompt_type === "confirm_value" ? "replace" : "submit")}>
              <PencilLine size={16} />{confirmation.prompt_type === "confirm_value" ? "使用新值" : "提交并继续"}
            </button>
            {!hasDefaultValue ? <button
              className={`icon-cancel ${requiredCancelArmed ? "cancel-armed" : ""}`}
              title={confirmation.input_required
                ? requiredCancelArmed ? "再次点击停止任务" : "必填项：再次点击将停止任务"
                : "使用默认值"}
              aria-label={confirmation.input_required
                ? requiredCancelArmed ? "再次点击停止任务" : "必填项"
                : "使用默认值"}
              disabled={submitting}
              onClick={() => void useDefaultOrCancelTask()}
            >
              {confirmation.input_required ? (
                requiredCancelArmed ? <Square size={14} fill="currentColor" /> : <X size={16} />
              ) : (
                <X size={16} />
              )}
            </button> : null}
          </div>
        </div>
      ) : null}

      {pending && confirmation.prompt_type === "confirmation" ? (
        <>
          <textarea value={comment} onChange={(event) => setComment(event.target.value)} placeholder="补充说明（可选）" disabled={submitting} rows={2} />
          <div className="confirmation-actions">
            <button className="button-primary" disabled={submitting} onClick={() => void resolveGeneric(true)}><Check size={16} />确认执行</button>
            <button className="button-secondary danger-text" disabled={submitting} onClick={() => void resolveGeneric(false)}><X size={16} />拒绝</button>
          </div>
        </>
      ) : null}

      {!pending ? (
        <div className="confirmation-result">
          {confirmation.status === "approved" ? `已提交${confirmation.selected_value ? `：${confirmation.selected_value}` : ""}` : "已取消"}
        </div>
      ) : null}
    </section>
  );
}
