------------------------------ MODULE AnalysisLifecycle ------------------------------
(***************************************************************************)
(* One call of analyze() (src/graphs/analyze_minuta_graph.py) and the row  *)
(* it writes in `analyses` plus its entries in `analysis_trail`            *)
(* (src/db/analyses.py, src/db/schema.sql).                                *)
(*                                                                         *)
(* The program is the code's real sequence of await points, one entry per *)
(* await (or per plain block that can raise). At each entry the step can  *)
(* succeed, raise an Exception, or be cancelled (asyncio.CancelledError).  *)
(* A DB write can fail before or after Postgres commits it. asyncpg's pool *)
(* waits for a cancelled statement to settle before it releases the       *)
(* connection (asyncpg/pool.py, _wait_for_cancellation), so by the time an *)
(* except block runs the statement has either committed or not.           *)
(*                                                                         *)
(* Design picks the code being checked:                                    *)
(*   "current"  the code before the fix (PR #31): guarded() per node,      *)
(*              catches Exception only, and only once the node's input     *)
(*              state has analysis_id; schema lets any status change.      *)
(*   "fixed"    analyze() owns the row: it makes the id before the graph   *)
(*              runs, iniciar inserts the row and its iniciar trail entry  *)
(*              in one transaction, and any BaseException ends the row     *)
(*              failed through a shielded UPDATE ... WHERE status =        *)
(*              'running'. The trigger freezes a finished row.             *)
(*   "fixed_*"  the fixed design with one safeguard removed, to show that  *)
(*              each property can fail.                                    *)
(* Assumption: the failure UPDATE reaches Postgres (the DB is up). A dead  *)
(* database cannot be written, by this or any design.                      *)
(***************************************************************************)
EXTENDS Naturals, Sequences

CONSTANT Design

Designs == {"current", "fixed", "fixed_catches_exception_only", "fixed_split_iniciar",
            "fixed_unguarded_failure"}
ASSUME Design \in Designs

Terminal == {"done", "unsupported", "failed"}
Statuses == {"none", "running"} \cup Terminal   \* "none": no row inserted yet
DbWrites == {"insert", "insert_iniciar", "trail", "finish"}

\* One await point. node = "" means outside every graph node (analyze() or LangGraph's loop).
Ins(k, node, what) == [k |-> k, node |-> node, what |-> what]
Ext(node, what) == Ins("ext", node, what)     \* await with no DB effect
Sync(node, what) == Ins("sync", node, what)   \* plain code: can raise, cannot be cancelled
Rec(node) == Ins("trail", node, node \o ": append_trail")
Between == Ext("", "LangGraph between nodes")

Prefix ==
    IF Design = "current"
    THEN << Ext("", "prepare_input") >>
    ELSE << Ext("", "prepare_input"), Ins("own", "", "analyze: new analysis_id, try begins") >>

Iniciar ==
    CASE Design = "current" ->
            << Sync("iniciar", "iniciar: mask check"), Ext("iniciar", "load_rules_snapshot"),
               Ins("insert", "iniciar", "start_analysis: INSERT"), Sync("iniciar", "tag_analysis"),
               Rec("iniciar") >>
      [] Design = "fixed_split_iniciar" ->
            << Sync("iniciar", "iniciar: mask check"), Ext("iniciar", "load_rules_snapshot"),
               Ins("insert", "iniciar", "start_analysis: INSERT"), Rec("iniciar"),
               Sync("iniciar", "tag_analysis") >>
      [] OTHER ->
            << Sync("iniciar", "iniciar: mask and id check"), Ext("iniciar", "load_rules_snapshot"),
               Ins("insert_iniciar", "iniciar", "start_analysis: INSERT + iniciar trail (one transaction)"),
               Sync("iniciar", "tag_analysis") >>

Node(n) == << Between, Ext(n, n \o ": Jev/LLM/search"), Rec(n) >>
Supported == Node("ficha") \o Node("triar") \o Node("buscar") \o Node("analisar")
Validar == << Between, Sync("validar", "validate_and_format"), Rec("validar"),
              Ins("finish", "validar", "finish_analysis") >>

Program(path) ==
    Prefix \o Iniciar \o Node("classificar")
    \o (IF path = "suportado" THEN Supported ELSE << >>)
    \o Validar \o << Ext("", "LangGraph returns to analyze") >>

VARIABLES pc,      \* index of the next await point in P
          phase,   \* "run", "handler" (analyze's except block) or "end"
          row,     \* status of the analyses row
          trail,   \* steps in analysis_trail, in seq order
          owned,   \* analyze() holds the analysis_id inside its try
          path,    \* classificar's verdict: supported minuta or not
          result,  \* how analyze() ended: "returned" or "raised"
          event    \* what the last step did, for reading a counterexample

vars == <<pc, phase, row, trail, owned, path, result, event>>

P == Program(path)

FinishStatus == IF path = "suportado" THEN "done" ELSE "unsupported"

\* The failure write ends the row failed only if it is still running.
\* guarded() in the current code runs finish_analysis, an UPDATE ... WHERE id = $1 with no status check.
GuardedFailure == Design \notin {"current", "fixed_unguarded_failure"}
\* analyses_guard rejects any UPDATE of a finished row.
TriggerFreezesTerminal == Design \notin {"current", "fixed_unguarded_failure"}

Catches(ins, e) ==
    IF Design = "current"
    THEN e = "error" /\ ins.node \notin {"", "iniciar"}   \* guarded(): state has analysis_id only after iniciar
    ELSE owned /\ (e = "error" \/ Design # "fixed_catches_exception_only")

Faults(k) == CASE k = "own" -> {} [] k = "sync" -> {"error"} [] OTHER -> {"error", "cancel"}

Apply(ins) ==
    /\ row' = CASE ins.k \in {"insert", "insert_iniciar"} -> "running"
                [] ins.k = "finish" -> FinishStatus
                [] OTHER -> row
    /\ trail' = CASE ins.k = "trail" -> Append(trail, ins.node)
                  [] ins.k = "insert_iniciar" -> << "iniciar" >>
                  [] OTHER -> trail

TypeOK ==
    /\ pc \in 1..Len(P)
    /\ phase \in {"run", "handler", "end"}
    /\ row \in Statuses
    /\ trail \in Seq({"iniciar", "classificar", "ficha", "triar", "buscar", "analisar", "validar"})
    /\ owned \in BOOLEAN
    /\ path \in {"suportado", "nao_suportado"}
    /\ result \in {"running", "returned", "raised"}

Init ==
    /\ pc = 1
    /\ phase = "run"
    /\ row = "none"
    /\ trail = << >>
    /\ owned = FALSE
    /\ path \in {"suportado", "nao_suportado"}
    /\ result = "running"
    /\ event = "start"

Proceed ==
    /\ phase = "run"
    /\ LET ins == P[pc] IN
        /\ IF ins.k \in DbWrites THEN Apply(ins) ELSE UNCHANGED <<row, trail>>
        /\ owned' = (owned \/ ins.k = "own")
        /\ pc' = IF pc = Len(P) THEN pc ELSE pc + 1
        /\ phase' = IF pc = Len(P) THEN "end" ELSE "run"
        /\ result' = IF pc = Len(P) THEN "returned" ELSE result
        /\ event' = ins.what \o ": ok"
        /\ UNCHANGED path

Fault ==
    /\ phase = "run"
    /\ LET ins == P[pc] IN
        \E e \in Faults(ins.k), committed \in (IF ins.k \in DbWrites THEN BOOLEAN ELSE {FALSE}):
            /\ IF committed THEN Apply(ins) ELSE UNCHANGED <<row, trail>>
            /\ phase' = IF Catches(ins, e) THEN "handler" ELSE "end"
            /\ result' = "raised"
            /\ event' = ins.what \o (IF committed THEN ": committed, then " ELSE ": ")
                        \o (IF e = "error" THEN "raised" ELSE "cancelled")
                        \o (IF Catches(ins, e) THEN " (caught)" ELSE " (not caught)")
            /\ UNCHANGED <<pc, owned, path>>

MarkFailed ==
    /\ phase = "handler"
    /\ row' = CASE row = "none" -> "none"                              \* UPDATE matches no row
                [] GuardedFailure -> IF row = "running" THEN "failed" ELSE row
                [] TriggerFreezesTerminal /\ row \in Terminal -> row   \* trigger rejects the UPDATE
                [] OTHER -> "failed"
    /\ phase' = "end"
    /\ event' = "failure write: status " \o row'
    /\ UNCHANGED <<pc, trail, owned, path, result>>

Finished == phase = "end" /\ UNCHANGED vars

Next == Proceed \/ Fault \/ MarkFailed \/ Finished

Spec == Init /\ [][Next]_vars

(***************************************************************************)
(* Properties                                                              *)
(***************************************************************************)
\* Once analyze() has returned or raised, its row is not left running.
NoRunEndsRunning == phase = "end" => row # "running"

\* A finished row has the iniciar entry first in its trail.
TrailStartsWithIniciar == row \in Terminal => Len(trail) > 0 /\ Head(trail) = "iniciar"

\* analyze() returns normally only after the row reached done or unsupported.
ReturnedMeansFinished == result = "returned" => row \in {"done", "unsupported"}

\* A finished status never changes.
TerminalNeverChanges == [][(row \in Terminal) => (row' = row)]_row
=====================================================================================
