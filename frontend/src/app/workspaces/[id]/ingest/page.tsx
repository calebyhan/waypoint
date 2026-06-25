"use client";

import { useCallback, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useSession } from "@/hooks/use-session";
import { apiFetch } from "@/lib/api";
import { toast } from "sonner";

interface Question {
  question: string;
  why: string;
}

type Step = "input" | "questions" | "loading" | "done";

export default function IngestPage() {
  const { id } = useParams<{ id: string }>();
  const { session } = useSession();
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [step, setStep] = useState<Step>("input");
  const [content, setContent] = useState("");
  const [questions, setQuestions] = useState<Question[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [analyzing, setAnalyzing] = useState(false);

  const handleAnalyze = useCallback(
    async (textContent: string) => {
      if (!textContent.trim() || !session) return;
      setAnalyzing(true);
      setStep("loading");

      try {
        const result = await apiFetch<{
          cached: boolean;
          questions?: Question[];
          decomposition?: unknown;
          extracted_content?: string;
        }>(`/workspaces/${id}/ingest`, {
          method: "POST",
          token: session.access_token,
          body: JSON.stringify({ content: textContent }),
        });

        if (result.cached || result.decomposition) {
          toast.success("PRD analyzed — plan ready");
          router.push(`/workspaces/${id}/proposal`);
        } else if (result.questions) {
          setQuestions(result.questions);
          setStep("questions");
        }
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Analysis failed");
        setStep("input");
      } finally {
        setAnalyzing(false);
      }
    },
    [id, session, router],
  );

  const handleFileUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file || !session) return;

      setAnalyzing(true);
      setStep("loading");

      const formData = new FormData();
      formData.append("file", file);

      try {
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL}/workspaces/${id}/ingest/upload`,
          {
            method: "POST",
            headers: { Authorization: `Bearer ${session.access_token}` },
            body: formData,
          },
        );

        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: "Upload failed" }));
          throw new Error(body.detail);
        }

        const result = await res.json();

        if (result.extracted_content) {
          setContent(result.extracted_content);
        }

        if (result.cached || result.decomposition) {
          toast.success("PRD analyzed — plan ready");
          router.push(`/workspaces/${id}/proposal`);
        } else if (result.questions) {
          setQuestions(result.questions);
          setStep("questions");
        }
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Upload failed");
        setStep("input");
      } finally {
        setAnalyzing(false);
      }
    },
    [id, session, router],
  );

  const handleSubmitAnswers = useCallback(async () => {
    if (!session) return;
    setAnalyzing(true);
    setStep("loading");

    try {
      const result = await apiFetch<{
        cached: boolean;
        decomposition?: unknown;
      }>(`/workspaces/${id}/ingest/answer`, {
        method: "POST",
        token: session.access_token,
        body: JSON.stringify({ content, answers }),
      });

      if (result.decomposition) {
        toast.success("Plan generated");
        router.push(`/workspaces/${id}/proposal`);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Decomposition failed");
      setStep("questions");
    } finally {
      setAnalyzing(false);
    }
  }, [id, session, content, answers, router]);

  return (
    <div className="mx-auto max-w-2xl p-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Ingest PRD</h1>
        <p className="text-muted-foreground">
          Paste your PRD, spec doc, or rough notes. Or upload a PDF.
        </p>
      </div>

      {step === "input" && (
        <Card>
          <CardHeader>
            <CardTitle>Document Content</CardTitle>
            <CardDescription>
              The AI will analyze this and propose a task breakdown.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Textarea
              placeholder="Paste your PRD or project description here..."
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={12}
              className="font-mono text-sm"
            />
            <div className="flex gap-2">
              <Button
                onClick={() => handleAnalyze(content)}
                disabled={!content.trim() || analyzing}
              >
                Analyze
              </Button>
              <Button
                variant="outline"
                onClick={() => fileInputRef.current?.click()}
              >
                Upload PDF
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf"
                onChange={handleFileUpload}
                className="hidden"
              />
            </div>
          </CardContent>
        </Card>
      )}

      {step === "questions" && (
        <Card>
          <CardHeader>
            <CardTitle>Clarifying Questions</CardTitle>
            <CardDescription>
              Answer these to get a better task breakdown, or skip to proceed
              directly.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {questions.map((q) => (
              <div key={q.question} className="space-y-2">
                <Label>{q.question}</Label>
                <p className="text-xs text-muted-foreground">{q.why}</p>
                <Input
                  value={answers[q.question] ?? ""}
                  onChange={(e) =>
                    setAnswers((prev) => ({
                      ...prev,
                      [q.question]: e.target.value,
                    }))
                  }
                  placeholder="Your answer..."
                />
              </div>
            ))}
            <div className="flex gap-2">
              <Button onClick={handleSubmitAnswers} disabled={analyzing}>
                Submit Answers
              </Button>
              <Button
                variant="ghost"
                onClick={() => {
                  setAnswers({});
                  handleSubmitAnswers();
                }}
                disabled={analyzing}
              >
                Skip Questions
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {step === "loading" && (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-lg font-medium">Analyzing your document...</p>
            <p className="mt-2 text-sm text-muted-foreground">
              The AI is decomposing your PRD into epics and tasks.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
