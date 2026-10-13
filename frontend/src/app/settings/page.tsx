"use client";

import { useEffect, useState } from "react";
import {
  Settings,
  Activity,
  Database,
  Sun,
  Moon,
  Monitor,
  CheckCircle,
  XCircle,
  Loader2,
  Wrench,
  Github,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useTheme } from "next-themes";
import * as api from "@/lib/api";
import type { GitHubConnection } from "@/lib/schemas";

interface HealthData {
  status: string;
  services: { name: string; healthy: boolean; message?: string }[];
  ollama: { status: string };
  qdrant: { status: string };
  database: { status: string };
}

interface ToolData {
  name: string;
  description: string;
}

export default function SettingsPage() {
  const { theme, setTheme } = useTheme();
  const [health, setHealth] = useState<HealthData | null>(null);
  const [tools, setTools] = useState<ToolData[]>([]);
  const [isLoadingHealth, setIsLoadingHealth] = useState(true);
  const [isLoadingTools, setIsLoadingTools] = useState(true);
  const [connName, setConnName] = useState("");
  const [connUrl, setConnUrl] = useState("");
  const [connStatus, setConnStatus] = useState<string | null>(null);
  const [githubConnection, setGithubConnection] = useState<GitHubConnection | null>(null);
  const [githubBusy, setGithubBusy] = useState(false);
  const [githubMessage, setGithubMessage] = useState("");

  useEffect(() => {
    async function loadHealth() {
      try {
        const data = await api.getHealth();
        setHealth(data as HealthData);
      } catch {
        setHealth(null);
      } finally {
        setIsLoadingHealth(false);
      }
    }

    async function loadTools() {
      try {
        const data = await api.getTools();
        setTools((data.tools ?? []) as ToolData[]);
      } catch {
        setTools([]);
      } finally {
        setIsLoadingTools(false);
      }
    }

    loadHealth();
    loadTools();
    api.getGitHubConnection().then(setGithubConnection).catch((cause: unknown) => {
      setGithubMessage(cause instanceof Error ? cause.message : "Could not load GitHub connection.");
    });
  }, []);

  const connectGitHub = async () => {
    setGithubBusy(true);
    setGithubMessage("");
    try {
      const { authorization_url } = await api.startGitHubConnection();
      window.location.assign(authorization_url);
    } catch (cause) {
      setGithubMessage(cause instanceof Error ? cause.message : "Could not start GitHub authorization.");
      setGithubBusy(false);
    }
  };

  const disconnectGitHub = async () => {
    if (!window.confirm("Disconnect GitHub and revoke this app's access to your account?")) return;
    setGithubBusy(true);
    setGithubMessage("");
    try {
      await api.disconnectGitHub();
      setGithubConnection(await api.getGitHubConnection());
      setGithubMessage("GitHub access revoked and disconnected.");
    } catch (cause) {
      setGithubMessage(cause instanceof Error ? cause.message : "Could not revoke GitHub access.");
    } finally {
      setGithubBusy(false);
    }
  };

  const handleAddConnection = async () => {
    if (!connName.trim() || !connUrl.trim()) return;
    try {
      await api.addSQLConnection(connName.trim(), connUrl.trim());
      setConnStatus("Connection added successfully");
      setConnName("");
      setConnUrl("");
    } catch (err) {
      setConnStatus(err instanceof Error ? err.message : "Failed to add connection");
    }
  };

  const StatusIcon = ({ status }: { status: string }) =>
    status === "ok" || status === "healthy" ? (
      <CheckCircle className="h-4 w-4 text-green-500" />
    ) : (
      <XCircle className="h-4 w-4 text-destructive" />
    );
  const optionalService = (name: string) => health?.services.find((service) => service.name === name);

  return (
    <div className="container mx-auto max-w-4xl px-4 py-6 sm:p-8">
      <div className="mb-6 flex items-center gap-3">
        <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-peach-soft text-peach-ink"><Settings className="h-6 w-6" aria-hidden="true" /></span>
        <div><h1 className="text-2xl font-bold">Settings</h1><p className="mt-1 text-sm text-muted-foreground">Make yourself at home.</p></div>
      </div>

      <div className="space-y-6">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2"><Github className="h-5 w-5" /><CardTitle className="text-base">GitHub Project Agent</CardTitle></div>
            <CardDescription>Connect your own GitHub account. The app stores encrypted, expiring credentials for your account only.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {githubConnection?.connected ? (
              <p className="text-sm">Connected as <span className="font-semibold">@{githubConnection.login}</span>{githubConnection.expires_at ? ` · current access token expires ${new Date(githubConnection.expires_at).toLocaleString()} and refreshes automatically` : ""}</p>
            ) : githubConnection?.configured ? (
              <p className="text-sm text-muted-foreground">Install the GitHub App only on repositories you want it to access, then authorize your account here.</p>
            ) : (
              <p className="text-sm text-muted-foreground">GitHub App credentials are not configured on this server yet.</p>
            )}
            <div className="flex flex-wrap gap-2">
              {githubConnection?.install_url && <Button asChild variant="outline"><a href={githubConnection.install_url} target="_blank" rel="noreferrer">Install GitHub App</a></Button>}
              {githubConnection?.connected ? (
                <Button variant="outline" onClick={() => void disconnectGitHub()} disabled={githubBusy}>{githubBusy ? <Loader2 className="animate-spin" /> : null}Disconnect and revoke</Button>
              ) : (
                <Button onClick={() => void connectGitHub()} disabled={githubBusy || !githubConnection?.configured}>{githubBusy ? <Loader2 className="animate-spin" /> : null}Connect GitHub</Button>
              )}
            </div>
            {githubMessage && <p role="status" className="text-sm text-muted-foreground">{githubMessage}</p>}
          </CardContent>
        </Card>

        {/* System Health */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Activity className="h-5 w-5" />
              <CardTitle className="text-base">System Health</CardTitle>
            </div>
            <CardDescription>Status of backend services</CardDescription>
          </CardHeader>
          <CardContent>
            {isLoadingHealth ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Checking services...
              </div>
            ) : health ? (
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="flex items-center gap-2 rounded-md border px-3 py-2">
                  <StatusIcon status={health.ollama.status} />
                  <div>
                    <div className="text-sm font-medium">Ollama</div>
                    <div className="text-[10px] text-muted-foreground">
                      {health.ollama.status}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2 rounded-md border px-3 py-2">
                  <StatusIcon status={health.qdrant.status} />
                  <div>
                    <div className="text-sm font-medium">Qdrant</div>
                    <div className="text-[10px] text-muted-foreground">
                      {health.qdrant.status}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2 rounded-md border px-3 py-2">
                  <StatusIcon status={health.database.status} />
                  <div>
                    <div className="text-sm font-medium">Database</div>
                    <div className="text-[10px] text-muted-foreground">
                      {health.database.status}
                    </div>
                  </div>
                </div>
                {([
                  ["finnhub_market_data", "Finnhub Market Data"],
                  ["comfyui", "ComfyUI"],
                ] as const).map(([name, label]) => {
                  const service = optionalService(name);
                  return (
                    <div key={name} className="flex items-center gap-2 rounded-md border px-3 py-2">
                      <StatusIcon status={service?.healthy ? "healthy" : "unavailable"} />
                      <div>
                        <div className="text-sm font-medium">{label}</div>
                        <div className="text-[10px] text-muted-foreground">
                          {service?.message ?? "Not reported"}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-sm text-destructive">
                Backend is not reachable. Make sure the FastAPI server is running on port 8000.
              </p>
            )}
          </CardContent>
        </Card>

        {/* Theme */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Appearance</CardTitle>
            <CardDescription>Choose your preferred color scheme</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex gap-2">
              {([
                { value: "light", label: "Light", Icon: Sun },
                { value: "dark", label: "Dark", Icon: Moon },
                { value: "system", label: "System", Icon: Monitor },
              ] as const).map(({ value, label, Icon }) => (
                <Button
                  key={value}
                  variant={theme === value ? "default" : "outline"}
                  size="sm"
                  onClick={() => setTheme(value)}
                >
                  <Icon className="mr-2 h-3 w-3" />
                  {label}
                </Button>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Database Connections */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Database className="h-5 w-5" />
              <CardTitle className="text-base">Database Connections</CardTitle>
            </div>
            <CardDescription>Add SQL databases for the SQL Agent to query</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label className="text-xs">Connection Name</Label>
                <Input
                  value={connName}
                  onChange={(e) => setConnName(e.target.value)}
                  placeholder="e.g. analytics"
                  className="text-sm"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Database URL</Label>
                <Input
                  value={connUrl}
                  onChange={(e) => setConnUrl(e.target.value)}
                  placeholder="sqlite:///path/to/db.sqlite"
                  className="text-sm"
                />
              </div>
            </div>
            <Button size="sm" onClick={handleAddConnection} disabled={!connName.trim() || !connUrl.trim()}>
              Add Connection
            </Button>
            {connStatus && (
              <p className="text-xs text-muted-foreground">{connStatus}</p>
            )}
          </CardContent>
        </Card>

        {/* Available Tools */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Wrench className="h-5 w-5" />
              <CardTitle className="text-base">Available Tools</CardTitle>
            </div>
            <CardDescription>Tools available to AI agents</CardDescription>
          </CardHeader>
          <CardContent>
            {isLoadingTools ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading tools...
              </div>
            ) : tools.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No tools loaded. Start the backend server.
              </p>
            ) : (
              <div className="space-y-2">
                {tools.map((tool) => (
                  <div key={tool.name} className="flex items-start gap-2 rounded-md border px-3 py-2">
                    <Badge variant="outline" className="mt-0.5 shrink-0 font-mono text-[10px]">
                      {tool.name}
                    </Badge>
                    <span className="text-xs text-muted-foreground">{tool.description}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
