"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
  Bot,
  Save,
  RotateCcw,
  Archive,
  Plus,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useTheme } from "next-themes";
import * as api from "@/lib/api";
import type { GitHubConnection } from "@/lib/schemas";
import type { GitHubRepository } from "@/lib/schemas";
import type { AgentProfile } from "@/lib/schemas";

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
  const [githubRepositories, setGithubRepositories] = useState<GitHubRepository[]>([]);
  const [agents, setAgents] = useState<AgentProfile[]>([]);
  const [selectedAgentName, setSelectedAgentName] = useState("");
  const [agentPrompt, setAgentPrompt] = useState("");
  const [agentDisplayName, setAgentDisplayName] = useState("");
  const [agentDescription, setAgentDescription] = useState("");
  const [agentBusy, setAgentBusy] = useState(false);
  const [agentMessage, setAgentMessage] = useState("");
  const [newAgentName, setNewAgentName] = useState("");
  const [newAgentDescription, setNewAgentDescription] = useState("");
  const [newAgentSource, setNewAgentSource] = useState("");
  const selectedAgentNameRef = useRef(selectedAgentName);
  selectedAgentNameRef.current = selectedAgentName;

  const selectedAgent = agents.find((agent) => agent.name === selectedAgentName);
  const creatableAgents = agents.filter((agent) => agent.inference && !agent.archived);

  const refreshAgents = useCallback(async (selectedName?: string) => {
    const catalog = await api.getAgentCatalogWithArchived();
    setAgents(catalog.agents);
    const nextName = selectedName ?? selectedAgentNameRef.current;
    const nextAgent = catalog.agents.find((agent) => agent.name === nextName) ?? catalog.agents[0];
    if (nextAgent) {
      setSelectedAgentName(nextAgent.name);
      setAgentPrompt(nextAgent.system_prompt);
      setAgentDisplayName(nextAgent.display_name);
      setAgentDescription(nextAgent.description);
    }
    const nextSource = catalog.agents.find((agent) => agent.inference && !agent.archived);
    if (nextSource) setNewAgentSource((current) => current || nextSource.name);
  }, []);

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
    void refreshAgents().catch((cause: unknown) => {
      setAgentMessage(cause instanceof Error ? cause.message : "Could not load agents.");
    });
    api.getGitHubConnection().then(async (connection) => {
      setGithubConnection(connection);
      if (connection.connected) {
        try {
          setGithubRepositories((await api.getGitHubRepositories()).repositories);
        } catch (cause) {
          setGithubMessage(cause instanceof Error ? cause.message : "Could not load GitHub repositories.");
        }
      }
    }).catch((cause: unknown) => {
      setGithubMessage(cause instanceof Error ? cause.message : "Could not load GitHub connection.");
    });
  }, [refreshAgents]);

  const saveAgent = async () => {
    if (!selectedAgent) return;
    setAgentBusy(true);
    setAgentMessage("");
    try {
      const input = selectedAgent.is_custom
        ? { display_name: agentDisplayName, description: agentDescription, system_prompt: agentPrompt }
        : { system_prompt: agentPrompt };
      const result = await api.updateAgent(selectedAgent.name, input);
      setAgents(result.agents);
      setAgentMessage("Agent saved. Changes apply to the next request.");
    } catch (cause) {
      setAgentMessage(cause instanceof Error ? cause.message : "Could not save agent.");
    } finally {
      setAgentBusy(false);
    }
  };

  const resetAgentPrompt = async () => {
    if (!selectedAgent) return;
    setAgentBusy(true);
    setAgentMessage("");
    try {
      const result = await api.updateAgent(selectedAgent.name, { system_prompt: null });
      setAgents(result.agents);
      const updated = result.agents.find((agent) => agent.name === selectedAgent.name);
      if (updated) setAgentPrompt(updated.system_prompt);
      setAgentMessage("Prompt reset to its default.");
    } catch (cause) {
      setAgentMessage(cause instanceof Error ? cause.message : "Could not reset prompt.");
    } finally {
      setAgentBusy(false);
    }
  };

  const createAgent = async () => {
    setAgentBusy(true);
    setAgentMessage("");
    try {
      const displayName = newAgentName.trim();
      const result = await api.createAgent({
        source_agent: newAgentSource,
        display_name: displayName,
        description: newAgentDescription,
      });
      const created = result.agents.find((agent) => agent.is_custom && agent.display_name === displayName);
      setAgents(result.agents);
      if (created) {
        setSelectedAgentName(created.name);
        setAgentPrompt(created.system_prompt);
        setAgentDisplayName(created.display_name);
        setAgentDescription(created.description);
      }
      setNewAgentName("");
      setNewAgentDescription("");
      setAgentMessage("Agent created.");
    } catch (cause) {
      setAgentMessage(cause instanceof Error ? cause.message : "Could not create agent.");
    } finally {
      setAgentBusy(false);
    }
  };

  const toggleAgentArchive = async () => {
    if (!selectedAgent?.is_custom) return;
    setAgentBusy(true);
    setAgentMessage("");
    try {
      const result = await api.updateAgent(selectedAgent.name, { archived: !selectedAgent.archived });
      setAgents(result.agents);
      setAgentMessage(selectedAgent.archived ? "Agent restored." : "Agent archived.");
    } catch (cause) {
      setAgentMessage(cause instanceof Error ? cause.message : "Could not update agent.");
    } finally {
      setAgentBusy(false);
    }
  };

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
      setGithubRepositories([]);
      setGithubMessage("GitHub access revoked and disconnected.");
    } catch (cause) {
      setGithubMessage(cause instanceof Error ? cause.message : "Could not revoke GitHub access.");
    } finally {
      setGithubBusy(false);
    }
  };

  const toggleGitHubRepository = async (repository: GitHubRepository) => {
    setGithubBusy(true);
    setGithubMessage("");
    try {
      await api.setGitHubRepositorySelection(repository.repository_id, !repository.selected);
      setGithubRepositories((current) => current.map((item) => item.repository_id === repository.repository_id
        ? { ...item, selected: !item.selected }
        : item));
    } catch (cause) {
      setGithubMessage(cause instanceof Error ? cause.message : "Could not update repository access.");
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
      <CheckCircle className="h-4 w-4 text-mint-ink" />
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
        {/* Agents */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2"><Bot className="h-5 w-5" /><CardTitle className="text-base">Agents</CardTitle></div>
            <CardDescription>Edit system prompts or create a reusable specialist from an existing agent type. Changes are shared across this installation.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {agents.length === 0 ? <p className="text-sm text-muted-foreground">Loading agents…</p> : <>
              <div className="grid gap-4 sm:grid-cols-[minmax(12rem,0.7fr)_minmax(0,1.3fr)]">
                <div className="space-y-3">
                  <Label htmlFor="managed-agent">Agent</Label>
                  <Select value={selectedAgentName} onValueChange={(value) => {
                    const agent = agents.find((item) => item.name === value);
                    if (!agent) return;
                    setSelectedAgentName(agent.name);
                    setAgentPrompt(agent.system_prompt);
                    setAgentDisplayName(agent.display_name);
                    setAgentDescription(agent.description);
                  }}>
                    <SelectTrigger id="managed-agent" className="w-full"><SelectValue /></SelectTrigger>
                    <SelectContent position="popper" align="start">
                      {agents.map((agent) => <SelectItem key={agent.name} value={agent.name}>{agent.display_name}{agent.archived ? " · archived" : ""}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  {selectedAgent?.is_custom && <>
                    <div className="space-y-1.5"><Label htmlFor="managed-agent-name">Name</Label><Input id="managed-agent-name" value={agentDisplayName} onChange={(event) => setAgentDisplayName(event.target.value)} maxLength={100} /></div>
                    <div className="space-y-1.5"><Label htmlFor="managed-agent-description">Description</Label><Input id="managed-agent-description" value={agentDescription} onChange={(event) => setAgentDescription(event.target.value)} maxLength={500} /></div>
                  </>}
                  {selectedAgent && <p className="text-xs text-muted-foreground">Type: {selectedAgent.target.replaceAll("_", " ")}{selectedAgent.is_custom ? " · custom specialist" : " · built in"}</p>}
                </div>
                <div className="space-y-2">
                  <Label htmlFor="managed-agent-prompt">System prompt</Label>
                  <textarea id="managed-agent-prompt" value={agentPrompt} onChange={(event) => setAgentPrompt(event.target.value)} maxLength={20000} disabled={!selectedAgent?.inference || selectedAgent.archived} className="min-h-52 w-full resize-y rounded-md border border-input bg-background px-3 py-2 font-sans text-sm leading-relaxed disabled:cursor-not-allowed disabled:opacity-60" />
                  <p className="text-xs text-muted-foreground">{selectedAgent?.inference ? <>Application supplied context and safety rules remain enforced. {agentPrompt.length}/20,000 characters.</> : "This built in profile does not use an LLM system prompt."}</p>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={() => void saveAgent()} disabled={agentBusy || !selectedAgent?.inference || selectedAgent.archived}><Save className="mr-2 h-4 w-4" />Save prompt</Button>
                {!selectedAgent?.is_custom && selectedAgent?.inference && <Button size="sm" variant="outline" onClick={() => void resetAgentPrompt()} disabled={agentBusy}><RotateCcw className="mr-2 h-4 w-4" />Reset to default</Button>}
                {selectedAgent?.is_custom && <Button size="sm" variant="outline" onClick={() => void toggleAgentArchive()} disabled={agentBusy}>{selectedAgent.archived ? <><Plus className="mr-2 h-4 w-4" />Restore agent</> : <><Archive className="mr-2 h-4 w-4" />Archive agent</>}</Button>}
              </div>
              <div className="space-y-3 border-t pt-4">
                <div><h3 className="text-sm font-semibold">Create specialist</h3><p className="text-xs text-muted-foreground">Copy one existing agent type, including its tools and inference settings. Agent types cannot be combined.</p></div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="space-y-1.5"><Label htmlFor="new-agent-name">Name</Label><Input id="new-agent-name" value={newAgentName} onChange={(event) => setNewAgentName(event.target.value)} placeholder="Research helper" maxLength={100} /></div>
                  <div className="space-y-1.5"><Label htmlFor="new-agent-type">Copy from</Label><Select value={newAgentSource} onValueChange={setNewAgentSource}><SelectTrigger id="new-agent-type" className="w-full"><SelectValue /></SelectTrigger><SelectContent position="popper" align="start">{creatableAgents.map((agent) => <SelectItem key={agent.name} value={agent.name}>{agent.display_name}</SelectItem>)}</SelectContent></Select></div>
                  <div className="space-y-1.5"><Label htmlFor="new-agent-description">Description</Label><Input id="new-agent-description" value={newAgentDescription} onChange={(event) => setNewAgentDescription(event.target.value)} placeholder="What this specialist is for" maxLength={500} /></div>
                </div>
                <Button size="sm" variant="outline" onClick={() => void createAgent()} disabled={agentBusy || !newAgentName.trim() || !newAgentDescription.trim() || !newAgentSource}><Plus className="mr-2 h-4 w-4" />Create agent</Button>
              </div>
              {agentMessage && <p role="status" className="text-sm text-muted-foreground">{agentMessage}</p>}
            </>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center gap-2"><Github className="h-5 w-5" /><CardTitle className="text-base">GitHub Project Agent</CardTitle></div>
            <CardDescription>Connect your own GitHub account. Grant Issues read/write for issue and comment posting; the app stores encrypted, expiring credentials for your account only.</CardDescription>
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
            {githubConnection?.connected && <div className="space-y-2 border-t pt-3">
              <p className="text-sm font-medium">Repositories available to the agent</p>
              {githubRepositories.length ? githubRepositories.map((repository) => <label key={repository.repository_id} className="flex items-center gap-3 rounded-md border px-3 py-2 text-sm">
                <input type="checkbox" checked={repository.selected} disabled={githubBusy} onChange={() => void toggleGitHubRepository(repository)} aria-label={`Allow agent to use ${repository.full_name}`} />
                <span className="min-w-0 flex-1">{repository.full_name}{repository.is_private ? " · private" : ""}</span>
                <span className="text-xs text-muted-foreground">{repository.default_branch}</span>
              </label>) : <p className="text-sm text-muted-foreground">No repositories were returned. Check the GitHub App installation and repository permissions.</p>}
              <p className="text-xs text-muted-foreground">Only checked repositories can be read by the project agent.</p>
            </div>}
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
                  placeholder="sqlite+aiosqlite:///path/to/db.sqlite"
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
