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
  const [submitting, setSubmitting] = useState(false);
  const [requiredCancelArmed, setRequiredCancelArmed] = useState(false);
  const pending = confirmation.status === "pending";
  const options = useMemo(
    () => confirmation.options || confirmation.actions?.filter((action) => action.id.startsWith("option_")) || [],
    [confirmation.actions, confirmation.options]
  );

  async function choose(option: ConfirmationOption) {
    if (!pending || submitting) return;
    setSubmitting(true);
    try {
      const value = option.value ?? option.label;
      if (String(value).trim() === "取消") {
        await reject(confirmation.confirmation_id, "用户取消");
      } else {
        await approve(confirmation.confirmation_id, value, option.id);
      }
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
      await approve(confirmation.confirmation_id, inputValue.trim(), actionId, comment);
    } finally {
      setSubmitting(false);
    }
  }

  async function useDefaultOrCancelTask() {
    if (!pending || submitting) return;
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
            {confirmation.prompt_type === "confirm_value" ? (
              <button className="button-secondary" disabled={submitting} onClick={() => void keepCurrent()}>
                <Check size={16} />沿用当前值
              </button>
            ) : null}
            <button className="button-primary" disabled={submitting || !inputValue.trim()} onClick={() => void submitInput(confirmation.prompt_type === "confirm_value" ? "replace" : "submit")}>
              <PencilLine size={16} />{confirmation.prompt_type === "confirm_value" ? "使用新值" : "提交并继续"}
            </button>
            <button
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
              {requiredCancelArmed ? <Square size={14} fill="currentColor" /> : <X size={16} />}
            </button>
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
