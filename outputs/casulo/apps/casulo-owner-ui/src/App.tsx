import { useEffect, useMemo, useRef, useState } from "react";
import { isTauriRuntime, startBridge, subscribeToBridgeRejections, subscribeToExperience } from "./bridge";
import { buildDesignTape, createInitialState, reduceExperience } from "./experience.mjs";
import { LivingForm } from "./LivingForm";
import type { BridgeStatusView, ExperienceEvent, ExperienceState } from "./types";

const SYNTHETIC_IDEA = "Quero um lugar calmo que transforme ideias faladas em pequenas ferramentas que eu possa abrir e continuar mudando.";

export default function App() {
  const [experience, setExperience] = useState<ExperienceState>(() => createInitialState());
  const [bridge, setBridge] = useState<BridgeStatusView | null>(null);
  const [designTape, setDesignTape] = useState<ExperienceEvent[]>([]);
  const [designIndex, setDesignIndex] = useState(0);
  const [advanced, setAdvanced] = useState(false);
  const [fatal, setFatal] = useState<string | null>(null);
  const [reducedMotion, setReducedMotion] = useState(false);
  const closeAdvancedRef = useRef<HTMLButtonElement>(null);
  const runtime = isTauriRuntime();

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    let unlisten: () => void = () => {};
    let unlistenRejections: () => void = () => {};
    let mounted = true;
    async function connect() {
      try {
        unlisten = await subscribeToExperience((event) => {
          setExperience((current) => {
            try {
              return reduceExperience(current, event);
            } catch {
              setFatal("Um evento incompatível foi recusado. O estado anterior foi preservado.");
              return current;
            }
          });
        });
        unlistenRejections = await subscribeToBridgeRejections(() => {
          if (mounted) setFatal("Um evento incompatível foi recusado. O estado anterior foi preservado.");
        });
        const status = await startBridge();
        if (mounted) {
          setBridge(status);
          if (status?.configuration_error) setFatal("O stream configurado foi recusado. Nenhum estado anterior foi alterado.");
        }
      } catch {
        if (mounted) setFatal("A ponte local não respondeu. Nenhuma criação foi perdida.");
      }
    }
    if (runtime) void connect();
    else buildDesignTape().then((tape) => mounted && setDesignTape(tape));
    return () => { mounted = false; unlisten(); unlistenRejections(); };
  }, [runtime]);

  useEffect(() => {
    if (!advanced) return;
    closeAdvancedRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setAdvanced(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [advanced]);

  const activeJob = experience.jobs.at(-1);
  const evidenceCount = useMemo(() => experience.jobs.reduce((sum, job) => sum + 1 + job.milestones.length, 0), [experience.jobs]);

  function accept(event: ExperienceEvent) {
    setExperience((current) => {
      try {
        setFatal(null);
        return reduceExperience(current, event);
      } catch (error) {
        setFatal(error instanceof Error ? error.message : "Evento recusado.");
        return current;
      }
    });
  }

  function advanceDesignTape() {
    const event = designTape[designIndex];
    if (!event) return;
    accept(event);
    setDesignIndex((current) => current + 1);
  }

  return (
    <main className="shell" data-mode={runtime ? "runtime" : "design"}>
      <header className="topbar">
        <div className="brand" aria-label="Casulo Owner">
          <span className="brand__mark" aria-hidden="true" />
          <span>Casulo</span>
        </div>
        <div className="topbar__actions">
          <span className={`mode-pill ${runtime ? "mode-pill--runtime" : "mode-pill--design"}`}>
            {runtime ? bridgeModeLabel(bridge?.mode) : "fita sintética · não é runtime"}
          </span>
          <button className="icon-button" type="button" onClick={() => setAdvanced(true)} aria-label="Abrir evidências e detalhes">•••</button>
        </div>
      </header>

      <section className="stage" aria-live="polite" aria-atomic="false">
        <div className="stage__copy">
          <p className="eyebrow">{experience.presence ? "PRESENÇA DISPONÍVEL" : "ABRINDO O CASULO"}</p>
          <h1>{headline(experience.form)}</h1>
          <p className="stage__notice">{fatal ?? experience.notice}</p>
        </div>

        <LivingForm state={fatal ? "RECOVERABLE_FAILURE" : experience.form} evidenceCount={evidenceCount} reducedMotion={reducedMotion} />

        <div className="dialogue" aria-label="Conversa com o Guia">
          {!runtime && designIndex >= 4 && <article className="message message--user">{SYNTHETIC_IDEA}</article>}
          {experience.messages.map((message) => (
            <article className="message message--guide" key={message.id}>
              <span>{message.text}</span>
              {!message.complete && <span className="stream-cursor" aria-label="resposta em andamento" />}
            </article>
          ))}
        </div>

        {activeJob && (
          <section className="creation-card" aria-label="Criação em andamento">
            <div className="creation-card__header">
              <div>
                <span className="creation-card__label">CRIAÇÃO LOCAL</span>
                <strong>{activeJob.summary}</strong>
              </div>
              <span className={`status-orb status-orb--${activeJob.status.toLowerCase()}`} aria-label={activeJob.status} />
            </div>
            <ol className="receipts">
              {activeJob.milestones.map((item) => (
                <li key={item.evidence}><span>{item.summary}</span><code>{item.evidence.slice(0, 10)}</code></li>
              ))}
            </ol>
          </section>
        )}
      </section>

      <footer className="composer-area">
        {!runtime ? (
          <div className="design-controls">
            <button className="primary-button" type="button" onClick={advanceDesignTape} disabled={designIndex >= designTape.length}>
              {designIndex >= designTape.length ? "Fita concluída" : "Próximo evento sintético"}
            </button>
            <span>{designIndex}/{designTape.length} eventos aplicados manualmente</span>
          </div>
        ) : (
          <div className="composer composer--disabled" aria-disabled="true">
            <label htmlFor="idea">Converse do seu jeito</label>
            <textarea id="idea" rows={1} disabled placeholder={bridge?.mode === "RUNTIME_VALIDATED" ? "A entrada do motor será conectada no próximo slice." : "Aguardando o stream local validado…"} />
            <button type="button" disabled aria-label="Enviar">↑</button>
          </div>
        )}
        <p className="boundary-note">Offline por padrão · sem API externa · progresso somente com evidência</p>
      </footer>

      {advanced && (
        <div className="drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setAdvanced(false); }}>
          <aside className="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="evidence-title">
            <div className="drawer-header">
              <div><p className="eyebrow">MODO AVANÇADO</p><h2 id="evidence-title">Evidência da projeção</h2></div>
              <button ref={closeAdvancedRef} className="icon-button" type="button" onClick={() => setAdvanced(false)} aria-label="Fechar detalhes">×</button>
            </div>
            <dl>
              <dt>Fonte</dt><dd>{runtime ? bridge?.mode ?? "indisponível" : "SYNTHETIC_DESIGN_TAPE"}</dd>
              <dt>Contrato</dt><dd><code>{bridge?.schema ?? "casulo.hosted-native-ux-contract/1.0"}</code></dd>
              <dt>Rede</dt><dd>{bridge?.network_enabled === false || !runtime ? "desativada" : "não verificada"}</dd>
              <dt>Shell</dt><dd>{bridge?.shell_enabled === false || !runtime ? "desativado" : "não verificado"}</dd>
              <dt>Eventos aceitos</dt><dd>{experience.seenEventIds.length}</dd>
              <dt>Último evento</dt><dd><code>{experience.lastEvent?.event_id ?? "nenhum"}</code></dd>
              <dt>Último hash</dt><dd><code>{experience.lastEvent?.event_hash ?? "nenhum"}</code></dd>
              <dt>Stream local</dt><dd><code>{bridge?.stream_path ?? "não conectado"}</code></dd>
            </dl>
            <p className="drawer-warning">Esta superfície só projeta estado. Grants, decisões, receipts e conclusão pertencem ao motor.</p>
          </aside>
        </div>
      )}
    </main>
  );
}

function headline(state: string): string {
  const labels: Record<string, string> = {
    SILENCE: "Um espaço para a ideia aparecer.",
    PRESENCE: "O que você quer tornar possível?",
    LISTENING: "Estou escutando.",
    THINKING: "Encontrando a forma inteira da ideia.",
    CONVERSATION: "A ideia está ficando nítida.",
    FIRST_FORM: "A primeira forma apareceu.",
    FORMATION: "A criação está ganhando corpo.",
    MATERIALIZED: "Agora existe algo para abrir.",
    CANCELLED: "Parei sem apagar o que já existia.",
    RECOVERABLE_FAILURE: "A criação foi preservada.",
  };
  return labels[state] ?? "O Casulo está presente.";
}

function bridgeModeLabel(mode?: string): string {
  if (mode === "RUNTIME_VALIDATED") return "motor local";
  if (mode === "RUNTIME_CONFIGURED") return "stream local configurado";
  if (mode === "CONFIGURATION_REJECTED") return "configuração recusada";
  return "aguardando motor";
}
