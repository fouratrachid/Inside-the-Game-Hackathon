import { useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { askQuestion } from "../api";
import { colors } from "../theme";
import type { ChatAnswer } from "../types";

export function traceLine(answer: ChatAnswer): string | null {
  const steps = (answer.tools_used ?? []).map(
    (step) => `${step.tool}(${Object.values(step.args ?? {}).join(", ")})`,
  );
  return steps.length ? `used: ${steps.join(" → ")}` : null;
}

export function ChatPanel({ base, sessionId }: { base: string; sessionId: string | null }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<ChatAnswer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed || !sessionId || busy) return;
    setBusy(true);
    setError(null);
    try {
      setAnswer(await askQuestion(base, sessionId, trimmed));
      setQuestion("");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not answer. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const trace = answer ? traceLine(answer) : null;
  return (
    <View style={styles.card}>
      <Text style={styles.title}>Ask the match</Text>
      {!sessionId ? <Text style={styles.muted}>Start a replay to ask questions.</Text> : null}
      <View style={styles.suggestions}>
        {["Who has created the better chances so far?", "What is field tilt?"].map((q) => (
          <Pressable
            key={q}
            onPress={() => submit(q)}
            disabled={!sessionId || busy}
            style={styles.chip}
            accessibilityRole="button"
          >
            <Text style={styles.chipText}>{q}</Text>
          </Pressable>
        ))}
      </View>
      <View style={styles.row}>
        <TextInput
          value={question}
          onChangeText={setQuestion}
          placeholder="Ask about the match so far"
          maxLength={500}
          style={styles.input}
          editable={!!sessionId && !busy}
          onSubmitEditing={() => submit(question)}
          accessibilityLabel="Your question"
        />
        <Pressable
          onPress={() => submit(question)}
          disabled={!sessionId || busy}
          style={[styles.button, (!sessionId || busy) && styles.disabled]}
          accessibilityRole="button"
          accessibilityLabel="Ask"
        >
          {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Ask</Text>}
        </Pressable>
      </View>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {answer ? (
        <View testID="answer">
          <Text style={styles.answer}>{answer.text}</Text>
          {answer.evidence?.length ? (
            <Text style={styles.muted}>
              Evidence: {answer.evidence.map((e) => `${e.minute}′ ${e.action}`).join(" · ")}
            </Text>
          ) : null}
          {trace ? <Text style={styles.trace}>{trace}</Text> : null}
          <Text style={styles.muted}>
            {answer.orchestrator ?? "Agent"} · {answer.provider ?? "AI"}
          </Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { padding: 16, borderRadius: 12, backgroundColor: colors.card, gap: 8 },
  title: { fontSize: 16, fontWeight: "700", color: colors.text },
  row: { flexDirection: "row", gap: 8 },
  input: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 8,
  },
  button: { backgroundColor: colors.accent, borderRadius: 8, paddingHorizontal: 16, justifyContent: "center" },
  disabled: { opacity: 0.5 },
  buttonText: { color: "#fff", fontWeight: "700" },
  suggestions: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { borderWidth: 1, borderColor: colors.line, borderRadius: 16, paddingHorizontal: 10, paddingVertical: 4 },
  chipText: { fontSize: 12, color: colors.text },
  answer: { fontSize: 15, lineHeight: 22, color: colors.text },
  muted: { fontSize: 12, color: colors.muted, marginTop: 4 },
  trace: { fontSize: 11, color: colors.muted, fontFamily: "monospace", marginTop: 4 },
  error: { color: colors.away },
});
