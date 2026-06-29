"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
import { Plus, Trash2, ArrowRight, ArrowLeft, Users, Settings, FileText } from "lucide-react";

const ROLES = [
  { value: "frontend", label: "Frontend" },
  { value: "backend", label: "Backend" },
  { value: "fullstack", label: "Full Stack" },
  { value: "devops", label: "DevOps" },
  { value: "design", label: "Design" },
  { value: "qa", label: "QA" },
  { value: "pm", label: "PM" },
] as const;

interface TeamMember {
  name: string;
  role: string;
  weekly_capacity_hours: number;
}

interface Question {
  question: string;
  why: string;
}

type Step = "team" | "config" | "prd" | "questions" | "loading";

export default function IngestPage() {
  const { id } = useParams<{ id: string }>();
  const { session } = useSession();
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [step, setStep] = useState<Step>("team");
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>([]);
  const [context, setContext] = useState({
    start_date: "",
    timeline: "",
    team_size: "",
    budget: "",
    tickets_per_member_per_week: 0,
    assign_day: -1,
  });
  const [content, setContent] = useState("");
  const [questions, setQuestions] = useState<Question[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [analyzing, setAnalyzing] = useState(false);

  const { data: existingTeam } = useQuery<TeamMember[]>({
    queryKey: ["team", id],
    queryFn: () =>
      apiFetch(`/workspaces/${id}/team`, { token: session!.access_token }),
    enabled: !!session,
  });

  useEffect(() => {
    if (existingTeam && existingTeam.length > 0 && teamMembers.length === 0) {
      setTeamMembers(
        existingTeam.map((m) => ({
          name: m.name,
          role: m.role,
          weekly_capacity_hours: m.weekly_capacity_hours,
        })),
      );
    }
  }, [existingTeam, teamMembers.length]);

  const addMember = () => {
    setTeamMembers((prev) => [
      ...prev,
      { name: "", role: "fullstack", weekly_capacity_hours: 40 },
    ]);
  };

  const updateMember = (index: number, field: keyof TeamMember, value: string | number) => {
    setTeamMembers((prev) =>
      prev.map((m, i) => (i === index ? { ...m, [field]: value } : m)),
    );
  };

  const removeMember = (index: number) => {
    setTeamMembers((prev) => prev.filter((_, i) => i !== index));
  };

  const syncTeam = useCallback(async () => {
    if (!session) return;
    const validMembers = teamMembers.filter((m) => m.name.trim());
    try {
      await apiFetch(`/workspaces/${id}/team/sync`, {
        method: "PUT",
        token: session.access_token,
        body: JSON.stringify({ members: validMembers }),
      });
    } catch {
      toast.error("Failed to save team");
    }
  }, [id, session, teamMembers]);

  const handleAnalyze = useCallback(
    async (textContent: string) => {
      if (!textContent.trim() || !session) return;
      setAnalyzing(true);
      setStep("loading");

      const validMembers = teamMembers.filter((m) => m.name.trim());
      const bodyContext = {
        ...context,
        team_size: validMembers.length > 0 ? `${validMembers.length} engineers` : context.team_size,
        team_members: validMembers,
      };

      try {
        const result = await apiFetch<{
          cached: boolean;
          questions?: Question[];
          decomposition?: unknown;
          extracted_content?: string;
        }>(`/workspaces/${id}/ingest`, {
          method: "POST",
          token: session.access_token,
          body: JSON.stringify({ content: textContent, context: bodyContext }),
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
        setStep("prd");
      } finally {
        setAnalyzing(false);
      }
    },
    [id, session, router, context, teamMembers],
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
            headers: {
              Authorization: `Bearer ${session.access_token}`,
              "ngrok-skip-browser-warning": "true",
            },
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
        setStep("prd");
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

    const validMembers = teamMembers.filter((m) => m.name.trim());
    const bodyContext = {
      ...context,
      team_size: validMembers.length > 0 ? `${validMembers.length} engineers` : context.team_size,
      team_members: validMembers,
    };

    try {
      const result = await apiFetch<{
        cached: boolean;
        decomposition?: unknown;
      }>(`/workspaces/${id}/ingest/answer`, {
        method: "POST",
        token: session.access_token,
        body: JSON.stringify({ content, context: bodyContext, answers }),
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
  }, [id, session, content, context, answers, router, teamMembers]);

  const stepIndex = ["team", "config", "prd", "questions", "loading"].indexOf(step);
  const steps = [
    { key: "team", label: "Team", icon: Users },
    { key: "config", label: "Project", icon: Settings },
    { key: "prd", label: "PRD", icon: FileText },
  ];

  return (
    <div className="mx-auto max-w-2xl p-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Ingest PRD</h1>
        <p className="text-muted-foreground">
          Set up your team, configure the project, then paste your PRD.
        </p>
      </div>

      {/* Step indicator */}
      <div className="flex items-center gap-2">
        {steps.map((s, i) => (
          <div key={s.key} className="flex items-center gap-2">
            {i > 0 && <div className="h-px w-8 bg-border" />}
            <button
              onClick={() => {
                if (i <= stepIndex && step !== "loading") setStep(s.key as Step);
              }}
              className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-sm transition-colors ${
                step === s.key
                  ? "bg-primary text-primary-foreground"
                  : i < stepIndex
                    ? "bg-primary/20 text-primary cursor-pointer"
                    : "bg-muted text-muted-foreground"
              }`}
            >
              <s.icon className="size-3.5" />
              {s.label}
            </button>
          </div>
        ))}
      </div>

      {/* Step 1: Team Setup */}
      {step === "team" && (
        <Card>
          <CardHeader>
            <CardTitle>Team Members</CardTitle>
            <CardDescription>
              Add your team members and their specialties. This helps assign tickets to the right people.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {teamMembers.length === 0 && (
              <p className="text-sm text-muted-foreground text-center py-4">
                No team members yet. Add your first team member below.
              </p>
            )}
            {teamMembers.map((member, i) => (
              <div key={i} className="flex items-end gap-2">
                <div className="flex-1 space-y-1.5">
                  {i === 0 && <Label>Name</Label>}
                  <Input
                    placeholder="e.g. Alice"
                    value={member.name}
                    onChange={(e) => updateMember(i, "name", e.target.value)}
                  />
                </div>
                <div className="w-36 space-y-1.5">
                  {i === 0 && <Label>Role</Label>}
                  <Select
                    value={member.role}
                    onValueChange={(v) => updateMember(i, "role", v ?? member.role)}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ROLES.map((r) => (
                        <SelectItem key={r.value} value={r.value}>
                          {r.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="w-20 space-y-1.5">
                  {i === 0 && <Label>Hrs/wk</Label>}
                  <Input
                    type="number"
                    min={1}
                    max={60}
                    value={member.weekly_capacity_hours}
                    onChange={(e) =>
                      updateMember(i, "weekly_capacity_hours", parseInt(e.target.value) || 40)
                    }
                  />
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => removeMember(i)}
                  className="shrink-0"
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
            ))}
            <Button variant="outline" onClick={addMember} className="w-full">
              <Plus className="size-4 mr-1.5" />
              Add Team Member
            </Button>
            <div className="flex justify-between pt-2">
              <div />
              <Button
                onClick={async () => {
                  await syncTeam();
                  setStep("config");
                }}
              >
                Next
                <ArrowRight className="size-4 ml-1.5" />
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 2: Project Config */}
      {step === "config" && (
        <Card>
          <CardHeader>
            <CardTitle>Project Configuration</CardTitle>
            <CardDescription>
              Set the project timeline and constraints. These help scope the task breakdown.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {teamMembers.filter((m) => m.name.trim()).length > 0 && (
              <div className="flex flex-wrap gap-1.5 pb-2">
                {teamMembers
                  .filter((m) => m.name.trim())
                  .map((m, i) => (
                    <Badge key={i} variant="secondary">
                      {m.name} — {ROLES.find((r) => r.value === m.role)?.label ?? m.role}
                    </Badge>
                  ))}
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="start_date">Start Date</Label>
                <Input
                  id="start_date"
                  type="date"
                  value={context.start_date}
                  onChange={(e) =>
                    setContext((prev) => ({ ...prev, start_date: e.target.value }))
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="timeline">Project Duration</Label>
                <Input
                  id="timeline"
                  placeholder="e.g. 6 weeks"
                  value={context.timeline}
                  onChange={(e) =>
                    setContext((prev) => ({ ...prev, timeline: e.target.value }))
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="budget">Budget</Label>
                <Input
                  id="budget"
                  placeholder="e.g. $50k"
                  value={context.budget}
                  onChange={(e) =>
                    setContext((prev) => ({ ...prev, budget: e.target.value }))
                  }
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ticket_pace">Ticket Pacing</Label>
              <div className="flex items-center gap-3">
                <Select
                  value={String(context.tickets_per_member_per_week)}
                  onValueChange={(v) =>
                    setContext((prev) => ({
                      ...prev,
                      tickets_per_member_per_week: parseFloat(v ?? "0"),
                    }))
                  }
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="0">No limit (back-to-back)</SelectItem>
                    <SelectItem value="1">1 ticket / person / week</SelectItem>
                    <SelectItem value="2">2 tickets / person / week</SelectItem>
                    <SelectItem value="3">3 tickets / person / week</SelectItem>
                    <SelectItem value="5">5 tickets / person / week</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <p className="text-xs text-muted-foreground">
                Controls how frequently each team member starts new tickets.
              </p>
            </div>
            {context.tickets_per_member_per_week > 0 && (
              <div className="space-y-1.5">
                <Label htmlFor="assign_day">Assign Day</Label>
                <Select
                  value={String(context.assign_day)}
                  onValueChange={(v) =>
                    setContext((prev) => ({
                      ...prev,
                      assign_day: parseInt(v ?? "-1"),
                    }))
                  }
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="-1">Any day</SelectItem>
                    <SelectItem value="0">Monday</SelectItem>
                    <SelectItem value="1">Tuesday</SelectItem>
                    <SelectItem value="2">Wednesday</SelectItem>
                    <SelectItem value="3">Thursday</SelectItem>
                    <SelectItem value="4">Friday</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Snap new ticket starts to a specific day of the week.
                </p>
              </div>
            )}
            <div className="flex justify-between pt-2">
              <Button variant="ghost" onClick={() => setStep("team")}>
                <ArrowLeft className="size-4 mr-1.5" />
                Back
              </Button>
              <Button onClick={() => setStep("prd")}>
                Next
                <ArrowRight className="size-4 ml-1.5" />
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 3: PRD Input */}
      {step === "prd" && (
        <Card>
          <CardHeader>
            <CardTitle>Document Content</CardTitle>
            <CardDescription>
              Paste your PRD, spec doc, or rough notes. Or upload a PDF. The AI will analyze this
              and propose a task breakdown with team assignments.
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
            <div className="flex justify-between pt-2">
              <Button variant="ghost" onClick={() => setStep("config")}>
                <ArrowLeft className="size-4 mr-1.5" />
                Back
              </Button>
              <div />
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 4: Clarifying Questions */}
      {step === "questions" && (
        <Card>
          <CardHeader>
            <CardTitle>Clarifying Questions</CardTitle>
            <CardDescription>
              Answer these to get a better task breakdown, or skip to proceed directly.
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

      {/* Loading */}
      {step === "loading" && (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-lg font-medium">Analyzing your document...</p>
            <p className="mt-2 text-sm text-muted-foreground">
              The AI is decomposing your PRD into epics and tasks
              {teamMembers.filter((m) => m.name.trim()).length > 0
                ? " with team assignments"
                : ""}
              .
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
