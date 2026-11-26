const OBJECT_TYPES = [
  "address",
  "address_group",
  "service",
  "service_group",
  "rule",
  "route",
  "zone",
  "interface",
  "ipsec_tunnel"
];

// Skeleton payloads offered by the "Add object" dialog, per object type.
const PAYLOAD_TEMPLATES = {
  address: { address: "", address_type: "ip", description: "" },
  address_group: { members: [], description: "" },
  service: { protocol: "tcp", port: "", source_port: "", description: "" },
  service_group: { members: [] },
  rule: {
    action: "allow",
    sources: [],
    destinations: [],
    services: [],
    source_zones: [],
    destination_zones: [],
    description: ""
  },
  interface: { ip: "", type: "", role: "", alias: "" },
  zone: { members: [] }
};

async function api(url, options = {}) {
  const response = await fetch(url, options);

  if (!response.ok) {
    let body = null;

    try {
      body = await response.json();
    } catch (_) {
      // Ignore JSON parse errors.
    }

    throw new Error(body && body.error ? body.error : `Request failed with status ${response.status}`);
  }

  const contentType = response.headers.get("Content-Type") || "";

  if (contentType.includes("application/json")) {
    return response.json();
  }

  return response.text();
}

// Read an NDJSON (one JSON object per line) streaming response and call
// onData for every parsed line.
async function readNdjson(response, onData) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    let index;

    while ((index = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, index).trim();
      buffer = buffer.slice(index + 1);
      if (line) onData(JSON.parse(line));
    }
  }

  const rest = buffer.trim();
  if (rest) onData(JSON.parse(rest));
}


// ---------------------------------------------------------------------------
// Dashboard (projects + firewalls, hosts both creation wizards)
// ---------------------------------------------------------------------------

function dashboard() {
  return {
    projects: [],
    firewalls: [],
    loading: true,
    error: "",
    showProjectWizard: false,
    showFirewallWizard: false,
    editing: null,

    async init() {
      try {
        const [projects, firewalls] = await Promise.all([
          api("/api/projects"),
          api("/api/firewalls")
        ]);
        this.projects = projects.items || [];
        this.firewalls = firewalls.items || [];
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },

    async reloadFirewalls() {
      try {
        const data = await api("/api/firewalls");
        this.firewalls = data.items || [];
      } catch (error) {
        this.error = error.message;
      }
    },

    // Re-fetch both lists in place (used after a delete so the dashboard
    // updates immediately — no full page reload needed).
    async reloadAll() {
      try {
        const [projects, firewalls] = await Promise.all([
          api("/api/projects"),
          api("/api/firewalls")
        ]);
        this.projects = projects.items || [];
        this.firewalls = firewalls.items || [];
      } catch (error) {
        this.error = error.message;
      }
    },

    // Shared delete handler. The server commits the delete and then answers
    // with a 302 redirect; following it (default fetch behavior) lands on the
    // target page with a final 200, which is the success signal. The lists
    // are then re-fetched in place — no full page reload needed.
    // (redirect:"manual" must NOT be used here: the post-redirect status is
    // unreliable across browsers and the old 3xx check never matched.)
    async deleteEntity(url, label) {
      try {
        const response = await fetch(url, { method: "POST" });

        if (!response.ok) {
          const data = await response.json().catch(() => null);
          throw new Error(data && data.error ? data.error : `Could not delete ${label} (HTTP ${response.status}).`);
        }

        await this.reloadAll();
      } catch (error) {
        alert(error.message);
      }
    },

    openEdit(firewall) {
      // Reset first so the edit modal is remounted (fresh component instance
      // that loads the current values for this firewall).
      this.editing = null;
      this.$nextTick(() => {
        this.editing = firewall;
      });
    },

    confirmDeleteProject(project) {
      if (!confirm(`Move project "${project.name}" (with its firewalls and objects) to the trash?`)) {
        return;
      }

      this.deleteEntity(`/projects/${project.id}/delete`, `project "${project.name}"`);
    },

    confirmDeleteFirewall(firewall) {
      if (!confirm(`Move firewall "${firewall.name}" (with its objects) to the trash?`)) {
        return;
      }

      this.deleteEntity(`/firewalls/${firewall.id}/delete`, `firewall "${firewall.name}"`);
    }
  };
}


// ---------------------------------------------------------------------------
// Firewalls page (card grid; creation goes through the 3-step wizard)
// ---------------------------------------------------------------------------

function firewallDashboard() {
  return {
    firewalls: [],
    loading: true,
    error: "",
    showForm: false,
    editing: null,

    async init() {
      try {
        const data = await api("/api/firewalls");
        this.firewalls = data.items || [];

        // Deep link: /firewalls?edit=<id> opens the edit modal directly.
        const editId = new URLSearchParams(window.location.search).get("edit");
        if (editId) {
          const fw = this.firewalls.find((f) => String(f.id) === editId);
          if (fw) this.openEdit(fw);
        }
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },

    async reloadFirewalls() {
      try {
        const data = await api("/api/firewalls");
        this.firewalls = data.items || [];
      } catch (error) {
        this.error = error.message;
      }
    },

    openEdit(firewall) {
      this.editing = null;
      this.$nextTick(() => {
        this.editing = firewall;
      });
    },

    confirmDelete(firewall) {
      if (!confirm(`Move firewall "${firewall.name}" (with its objects) to the trash?`)) {
        return;
      }

      this.deleteEntity(firewall);
    },

    // See dashboard().deleteEntity: follow the post-delete 302 (final 200 =
    // success) and refresh the list in place instead of reloading the page.
    async deleteEntity(firewall) {
      try {
        const response = await fetch(`/firewalls/${firewall.id}/delete`, {
          method: "POST"
        });

        if (!response.ok) {
          const data = await response.json().catch(() => null);
          throw new Error(data && data.error ? data.error : `Could not delete firewall "${firewall.name}" (HTTP ${response.status}).`);
        }

        await this.reloadFirewalls();
      } catch (error) {
        alert(error.message);
      }
    }
  };
}


// ---------------------------------------------------------------------------
// Project creation wizard (3 steps)
// Step 1: name + description
// Step 2: attach existing firewalls (with or without an imported config)
// Step 3: validation summary -> creates the project and opens its page
// ---------------------------------------------------------------------------

function projectWizard() {
  return {
    step: 1,
    stepError: "",
    name: "",
    description: "",
    attachable: [],
    selected: [],
    loadingAttachable: true,
    submitting: false,
    submitError: "",

    async init() {
      try {
        const data = await api("/api/firewalls");
        // Every firewall can be attached — also without an imported
        // configuration (it can be imported later from the project page).
        this.attachable = data.items || [];
      } catch (_) {
        this.attachable = [];
      } finally {
        this.loadingAttachable = false;
      }
    },

    fw(firewallId) {
      return this.attachable.find((fw) => fw.id === firewallId);
    },

    toggle(firewallId) {
      const index = this.selected.indexOf(firewallId);
      if (index > -1) {
        this.selected.splice(index, 1);
      } else {
        this.selected.push(firewallId);
      }
    },

    next() {
      if (this.step === 1) {
        const value = this.name.trim();
        if (!value) {
          this.stepError = "Project name is required.";
          return;
        }
        if (value.length < 2 || value.length > 100) {
          this.stepError = "Project name must be between 2 and 100 characters.";
          return;
        }
      }
      this.stepError = "";
      if (this.step < 3) this.step += 1;
    },

    back() {
      if (this.step > 1) this.step -= 1;
    },

    async create() {
      this.submitting = true;
      this.submitError = "";

      try {
        const data = await api("/api/projects", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: this.name.trim(),
            description: this.description.trim() || null,
            firewall_ids: this.selected
          })
        });

        // Step 3 requirement: open the newly created project page immediately.
        location.href = `/projects/${data.item.id}`;
      } catch (error) {
        this.submitError = error.message;
        this.submitting = false;
      }
    }
  };
}


// ---------------------------------------------------------------------------
// Firewall creation wizard (3 steps)
// Step 1: basic data (name, vendor, model, mgmt IP, auth, description)
// Step 2: import configuration (file upload or REST API, connectivity check)
// Step 3: create the firewall; option to skip the import
// ---------------------------------------------------------------------------

function firewallWizard(objectTypes) {
  return {
    objectTypes: objectTypes && objectTypes.length ? objectTypes : OBJECT_TYPES,
    step: 1,
    stepError: "",
    name: "",
    vendor: "",
    model: "",
    management_ip: "",
    auth_mode: "password",
    api_username: "",
    api_password: "",
    api_token: "",
    description: "",
    // Step 2
    source: "file",
    url: "",
    connBusy: false,
    connResult: null,
    // Step 3
    importMode: "import",
    creating: false,
    created: null,
    progress: 0,
    progressActive: false,
    progressStage: "",
    importResult: null,
    importError: "",

    next() {
      if (this.step === 1) {
        if (!this.name.trim()) {
          this.stepError = "Name is required.";
          return;
        }
        if (!this.vendor) {
          this.stepError = "Select a vendor.";
          return;
        }
      }
      this.stepError = "";
      if (this.step < 3) this.step += 1;
    },

    back() {
      // Back is allowed before the firewall exists, and also after it exists
      // when the import failed (e.g. "No configuration file chosen") — the
      // user goes back to step 2 to pick a file / fix the URL. It is NOT
      // allowed after a successful creation (skip or import done): the
      // "Create firewall" button would try to create it a second time.
      if (this.step > 1 && !this.creating && (!this.created || this.importError)) {
        this.step -= 1;
        this.stepError = "";
      }
    },

    async checkConnectivity() {
      this.connBusy = true;
      this.connResult = null;

      try {
        this.connResult = await api("/api/connectivity", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            management_ip: this.management_ip,
            vendor: this.vendor,
            auth_mode: this.auth_mode,
            api_username: this.api_username,
            api_password: this.api_password,
            api_token: this.api_token
          })
        });
      } catch (error) {
        this.connResult = { ok: false, detail: error.message };
      } finally {
        this.connBusy = false;
      }
    },

    async create() {
      this.creating = true;
      this.importError = "";
      this.importResult = null;
      this.progress = 0;

      try {
        if (this.created) {
          // The firewall already exists (a previous attempt created it and
          // the import failed): retry only the import, never re-create.
          if (this.importMode === "import") {
            await this.runImport(this.created.id);
          }
          return;
        }

        const body = {
          name: this.name.trim(),
          vendor: this.vendor,
          model: this.model.trim() || null,
          management_ip: this.management_ip.trim() || null,
          auth_mode: this.auth_mode,
          description: this.description.trim() || null
        };

        if (this.auth_mode === "password") {
          body.api_username = this.api_username || null;
          body.api_password = this.api_password || null;
        } else {
          body.api_token = this.api_token || null;
        }

        const data = await api("/api/firewalls", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body)
        });

        this.created = data.item;

        if (this.importMode === "import") {
          await this.runImport(this.created.id);
        }
      } catch (error) {
        this.importError = error.message;
        this.progressActive = false;
      } finally {
        this.creating = false;
      }
    },

    runImport(firewallId) {
      this.progressActive = true;
      this.progress = 0;
      this.progressStage = "Starting import...";

      const formData = new FormData();
      formData.append("firewall_id", String(firewallId));
      formData.append("object_types", this.objectTypes.join(","));

      if (this.source === "file") {
        const input = this.$refs.fileInput;
        const file = input ? input.files[0] : null;

        if (!file) {
          this.importError =
            "No configuration file chosen. Pick a file in step 2 or select “Skip import”.";
          this.progressActive = false;
          return Promise.resolve();
        }

        formData.append("source_type", "file");
        formData.append("config_file", file);

        // XHR: real upload progress bar, then parse/import until the JSON answer.
        return new Promise((resolve) => {
          const xhr = new XMLHttpRequest();
          xhr.open("POST", "/api/import");

          xhr.upload.onprogress = (event) => {
            if (event.lengthComputable) {
              this.progress = Math.round((event.loaded / event.total) * 50);
              this.progressStage = "Uploading file...";
            }
          };

          xhr.upload.onload = () => {
            this.progressStage = "Parsing and importing...";
          };

          xhr.onload = () => {
            this.progressActive = false;
            this.progress = xhr.status >= 200 && xhr.status < 300 ? 100 : 0;

            try {
              const data = JSON.parse(xhr.responseText);
              if (xhr.status >= 200 && xhr.status < 300) {
                this.importResult = data;
              } else {
                this.importError = data.error || "Import failed.";
              }
            } catch (_) {
              this.importError = `Import failed (HTTP ${xhr.status}).`;
            }
            resolve();
          };

          xhr.onerror = () => {
            this.progressActive = false;
            this.importError = "Network error during import.";
            resolve();
          };

          xhr.send(formData);
        });
      }

      formData.append("source_type", "url");
      formData.append("url", this.url);

      // REST source: streamed progress (connect / download / parse / import).
      return (async () => {
        try {
          const response = await fetch("/api/import/stream", {
            method: "POST",
            body: formData
          });

          if (!response.ok) {
            let message = "Import failed.";
            try {
              const data = await response.json();
              message = data.error || message;
            } catch (_) {
              // Not a JSON body.
            }
            this.importError = message;
            return;
          }

          await readNdjson(response, (line) => {
            if (line.event === "progress") {
              this.progress = line.percent;
              this.progressStage = line.detail;
            } else if (line.event === "done") {
              this.progress = 100;
              this.importResult = line;
            } else if (line.event === "error") {
              this.importError = line.error;
            }
          });
        } catch (error) {
          this.importError = error.message;
        } finally {
          this.progressActive = false;
        }
      })();
    },

    objectsUrl() {
      return this.created ? `/objects?firewall_id=${this.created.id}` : "/objects";
    },

    done() {
      location.href = "/";
    }
  };
}


// ---------------------------------------------------------------------------
// Firewall edit modal
// Loads the current values (including the stored credentials) from
// GET /api/firewalls/<id>, saves via PATCH /api/firewalls/<id>, then calls
// onSaved so the page can refresh its firewall list.
// ---------------------------------------------------------------------------

function firewallEdit(vendorChoices, firewallId, onSaved) {
  return {
    open: true,
    loading: false,
    loadError: "",
    saving: false,
    saveError: "",
    name: "",
    vendor: vendorChoices && vendorChoices.length ? vendorChoices[0] : "",
    model: "",
    management_ip: "",
    auth_mode: "password",
    api_username: "",
    api_password: "",
    api_token: "",
    description: "",

    async init() {
      if (!firewallId) return;

      this.loading = true;

      try {
        const data = await api(`/api/firewalls/${firewallId}`);
        const fw = data.item;
        this.name = fw.name;
        this.vendor = fw.vendor;
        this.model = fw.model || "";
        this.management_ip = fw.management_ip || "";
        this.auth_mode = fw.auth_mode || "password";
        this.api_username = fw.api_username || "";
        this.api_password = fw.api_password || "";
        this.api_token = fw.api_token || "";
        this.description = fw.description || "";
      } catch (error) {
        this.loadError = error.message;
      } finally {
        this.loading = false;
      }
    },

    close() {
      this.open = false;
    },

    async save() {
      if (!firewallId || this.saving) return;

      this.saving = true;
      this.saveError = "";

      const body = {
        name: this.name.trim(),
        vendor: this.vendor,
        model: this.model.trim() || null,
        management_ip: this.management_ip.trim() || null,
        auth_mode: this.auth_mode,
        description: this.description.trim() || null
      };

      // The server clears the inactive credential side; mirror that here.
      if (this.auth_mode === "password") {
        body.api_username = this.api_username || null;
        body.api_password = this.api_password || null;
        body.api_token = null;
      } else {
        body.api_username = null;
        body.api_password = null;
        body.api_token = this.api_token || null;
      }

      try {
        await api(`/api/firewalls/${firewallId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body)
        });
        this.open = false;
        if (typeof onSaved === "function") onSaved();
      } catch (error) {
        this.saveError = error.message;
      } finally {
        this.saving = false;
      }
    }
  };
}


// ---------------------------------------------------------------------------
// Object list (scoped by navigation context) with staged changes
// ---------------------------------------------------------------------------

function objectTable(columns) {
  const params = new URLSearchParams(window.location.search);

  const scope = {
    project_id: params.get("project_id") || "",
    firewall_id: params.get("firewall_id") || "",
    object_type: params.get("object_type") || ""
  };

  return {
    columns: columns || [],
    scope,
    rows: [],
    total: 0,
    page: 1,
    perPage: 25,
    totalPages: 1,
    loading: true,
    error: "",
    searchField: "any",
    searchTerm: "",

    // Status filter (toolbar dropdown): "all" (no filter) or one of
    // "included" / "modified" / "deleted".
    statusFilter: "all",

    // Selection for the "Include in the export" / "Remove from export"
    // buttons. The checkboxes only select rows — nothing is sent to the
    // server on check/uncheck. The selection mirrors the persisted
    // export_included state (tagged rows are preselected), so it always
    // reflects what is actually included in the export.
    checked: [],
    tagging: false,
    tagMsg: "",
    tagError: "",

    // Staged (not yet committed) changes, applied by the Validate button.
    pending: [],
    committing: false,
    commitMsg: "",
    commitError: "",

    modal: {
      open: false,
      id: null,
      object: null,
      history: [],
      tab: "details",
      name: "",
      description: "",
      payloadText: "",
      // Visual form fields for the payload (see buildPayloadFields):
      // [{key, kind: text|number|boolean|list|json, value}]
      fields: []
    },

    addOpen: false,
    addName: "",
    addDescription: "",
    addPayloadText: "{}",

    init() {
      this.load();
    },

    // Rows to render: staged "create" rows first, then the fetched rows with
    // staged edits applied and staged deletions removed.
    get displayRows() {
      const out = [];
      let newSeq = 0;

      for (const change of this.pending) {
        if (change.op !== "create") continue;
        newSeq += 1;
        out.push({
          id: `new-${newSeq}`,
          _new: true,
          object_type: change.object_type,
          name: change.name,
          description: change.description || "",
          payload: change.payload || {},
          firewall_name: "",
          updated_by: "(staged)"
        });
      }

      for (const row of this.rows) {
        const staged = this.pendingFor(row.id);
        if (staged && staged.op === "delete") continue;
        if (staged && staged.op === "update") {
          out.push({
            ...row,
            _staged: true,
            name: staged.name !== undefined ? staged.name : row.name,
            description: staged.description !== undefined ? staged.description : row.description,
            payload: staged.payload !== undefined ? staged.payload : row.payload
          });
        } else {
          out.push(row);
        }
      }

      return out;
    },

    pendingFor(id) {
      return this.pending.find((change) => change.id === id);
    },

    async load() {
      const query = new URLSearchParams();

      if (this.scope.project_id) query.set("project_id", this.scope.project_id);
      if (this.scope.firewall_id) query.set("firewall_id", this.scope.firewall_id);
      if (this.scope.object_type) query.set("object_type", this.scope.object_type);
      if (this.searchTerm) {
        if (this.searchField === "any") {
          query.set("search", this.searchTerm);
        } else {
          query.set(this.searchField, this.searchTerm);
        }
      }
      if (this.statusFilter !== "all") {
        query.set("filter", this.statusFilter);
      }
      // Deleted objects stay in the list (greyed out, with a Restore
      // button) instead of disappearing from the page.
      query.set("include_deleted", "true");
      query.set("page", String(this.page));
      query.set("per_page", String(this.perPage));

      this.loading = true;
      this.error = "";

      try {
        const data = await api(`/api/objects?${query.toString()}`);
        this.rows = data.items || [];
        this.total = data.total || 0;
        this.totalPages = data.total_pages || 1;
        this.syncChecked();
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },

    changePerPage() {
      this.page = 1;
      this.load();
    },

    gotoPage(page) {
      if (page < 1 || page > this.totalPages) return;
      this.page = page;
      this.load();
    },

    cellValue(row, key) {
      if (key === "_summary") {
        const payload = row.payload || {};
        return [
          payload.action,
          payload.address,
          payload.ip,
          payload.protocol,
          payload.port,
          payload.members && payload.members.length ? `${payload.members.length} members` : null,
          payload.sources && payload.sources.length ? `${payload.sources.length} sources` : null,
          payload.destinations && payload.destinations.length ? `${payload.destinations.length} destinations` : null
        ]
          .filter(Boolean)
          .join(" · ");
      }

      if (key === "_enabled") {
        return row.payload && row.payload.disabled ? "disabled" : "enabled";
      }

      let current = row;
      for (const part of key.split(".")) {
        if (current == null) return "";
        current = current[part];
      }

      if (Array.isArray(current)) return current.join(", ");
      return current == null ? "" : String(current);
    },

    // Rebuild the selection from the persisted tag state: every tagged row
    // shown on the current page is selected, so the checkboxes always mirror
    // what is actually included in the export.
    syncChecked() {
      this.checked = this.selectableRows
        .filter((row) => row.export_included)
        .map((row) => row.id);
    },

    isChecked(id) {
      return this.checked.includes(id);
    },

    // Pure selection: no server call on check/uncheck — the selection is
    // applied only by the "Include in the export" / "Remove from export"
    // buttons.
    toggleCheck(id) {
      const index = this.checked.indexOf(id);
      if (index > -1) {
        this.checked.splice(index, 1);
      } else {
        this.checked.push(id);
      }
    },

    get selectableRows() {
      // Deleted rows cannot be tagged for the export (they are excluded
      // from generated configurations until restored).
      return this.displayRows.filter((row) => !row._new && !row.is_deleted);
    },

    get allPageChecked() {
      const selectable = this.selectableRows;
      return selectable.length > 0 && selectable.every((row) => this.checked.includes(row.id));
    },

    // Header checkbox: pure selection (select all / clear the page).
    togglePage() {
      this.checked = this.allPageChecked ? [] : this.selectableRows.map((row) => row.id);
    },

    // Selected rows that each toolbar button will actually change.
    get toIncludeCount() {
      return this.selectableRows.filter(
        (row) => this.checked.includes(row.id) && !row.export_included
      ).length;
    },

    get toRemoveCount() {
      return this.selectableRows.filter(
        (row) => this.checked.includes(row.id) && row.export_included
      ).length;
    },

    // Tag (include=true) or untag (include=false) the selected objects as
    // "included in the config export" via POST /api/objects/export-include.
    // Called only by the toolbar buttons, never by the checkboxes.
    async setExportIncluded(ids, include) {
      if (ids.length === 0 || this.tagging) {
        return;
      }

      this.tagging = true;
      this.tagMsg = "";
      this.tagError = "";

      try {
        const data = await api("/api/objects/export-include", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ object_ids: ids, include })
        });

        this.tagMsg = data.message;
        await this.load(); // server state wins; load() resyncs the selection
        setTimeout(() => {
          this.tagMsg = "";
        }, 6000);
      } catch (error) {
        this.tagError = error.message;
      } finally {
        this.tagging = false;
      }
    },

    // Toolbar: include the selected (still untagged) rows in the export.
    includeInExport() {
      const ids = this.selectableRows
        .filter((row) => this.checked.includes(row.id) && !row.export_included)
        .map((row) => row.id);
      this.setExportIncluded(ids, true);
    },

    // Toolbar: remove the selected (tagged) rows from the export.
    removeFromExport() {
      const ids = this.selectableRows
        .filter((row) => this.checked.includes(row.id) && row.export_included)
        .map((row) => row.id);
      this.setExportIncluded(ids, false);
    },

    openEdit(row) {
      if (row.is_deleted) {
        alert(`"${row.name}" is in the trash. Restore it first to modify it.`);
        return;
      }

      const staged = this.pendingFor(row.id);
      if (staged && staged.op === "delete") {
        alert("This object is staged for deletion. Discard the deletion first.");
        return;
      }

      this.modal.open = true;
      this.modal.id = row.id;
      this.modal.object = row;
      this.modal.tab = "details";
      this.modal.name = staged && staged.op === "update" && staged.name !== undefined ? staged.name : row.name;
      this.modal.description =
        staged && staged.op === "update" && staged.description !== undefined
          ? staged.description
          : row.description || "";
      const payload = staged && staged.op === "update" && staged.payload !== undefined ? staged.payload : row.payload;
      this.modal.payloadText = JSON.stringify(payload || {}, null, 2);
      this.modal.fields = this.buildPayloadFields(payload);
      this.loadHistory();
    },

    // Build one visual form field per payload key: scalars -> text/number/
    // boolean inputs, arrays of scalars -> one item per line, objects and
    // arrays of objects -> JSON textareas.
    buildPayloadFields(payload) {
      const fields = [];

      for (const [key, value] of Object.entries(payload || {})) {
        if (value === null) {
          fields.push({ key, kind: "text", value: "" });
        } else if (typeof value === "boolean") {
          fields.push({ key, kind: "boolean", value });
        } else if (typeof value === "number") {
          fields.push({ key, kind: "number", value: String(value) });
        } else if (typeof value === "string") {
          fields.push({ key, kind: "text", value });
        } else if (Array.isArray(value)) {
          const scalar = value.every((v) => v === null || typeof v !== "object");
          fields.push(
            scalar
              ? {
                  key,
                  kind: "list",
                  value: value.map((v) => (v === null ? "" : String(v))).join("\n")
                }
              : { key, kind: "json", value: JSON.stringify(value, null, 2) }
          );
        } else {
          fields.push({ key, kind: "json", value: JSON.stringify(value, null, 2) });
        }
      }

      return fields;
    },

    // Overlay the visual fields' values on top of the parsed payload JSON
    // (the fields win for the keys they cover). Throws on invalid input.
    applyPayloadFields(payload) {
      for (const field of this.modal.fields) {
        if (field.kind === "boolean") {
          payload[field.key] = field.value;
        } else if (field.kind === "number") {
          const text = String(field.value).trim();
          if (text === "") {
            payload[field.key] = null;
          } else {
            const num = Number(text);
            if (Number.isNaN(num)) {
              throw new Error(`'${field.key}' must be a number.`);
            }
            payload[field.key] = num;
          }
        } else if (field.kind === "list") {
          payload[field.key] = String(field.value)
            .split(/[\n,]/)
            .map((s) => s.trim())
            .filter((s) => s !== "");
        } else if (field.kind === "json") {
          const text = String(field.value).trim();
          payload[field.key] = text === "" ? null : JSON.parse(text);
        } else {
          payload[field.key] = field.value;
        }
      }

      return payload;
    },

    // Rebuild the visual fields from the (possibly hand-edited) Payload JSON
    // textarea, so the form and the JSON never drift apart.
    resyncFields() {
      let payload;

      try {
        payload = JSON.parse(this.modal.payloadText);
      } catch (_) {
        alert("Payload JSON must be valid JSON before re-syncing the fields.");
        return;
      }

      if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
        alert("Payload must be a JSON object.");
        return;
      }

      this.modal.fields = this.buildPayloadFields(payload);
    },

    closeModal() {
      this.modal.open = false;
    },

    loadHistory() {
      if (!this.modal.id || String(this.modal.id).startsWith("new-")) {
        return;
      }

      api(`/api/objects/${this.modal.id}/history`)
        .then((data) => {
          this.modal.history = data.items || [];
        })
        .catch(() => {
          this.modal.history = [];
        });
    },

    // Validate the modal edits: stage the update AND commit it straight
    // away (single-change commit). Other staged changes stay pending and can
    // be committed with the toolbar Validate button. If the commit fails the
    // change remains staged.
    async validateFromModal() {
      let payload;

      try {
        payload = JSON.parse(this.modal.payloadText);
      } catch (_) {
        alert("Payload JSON must be valid JSON.");
        return;
      }

      if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
        alert("Payload must be a JSON object.");
        return;
      }

      try {
        this.applyPayloadFields(payload);
      } catch (error) {
        alert(`Invalid payload field: ${error.message}`);
        return;
      }

      if (!this.modal.name.trim()) {
        alert("Name is required.");
        return;
      }

      const entry = {
        op: "update",
        id: this.modal.id,
        name: this.modal.name.trim(),
        description: this.modal.description,
        payload
      };

      const index = this.pending.findIndex(
        (change) => change.id === this.modal.id && change.op === "update"
      );

      if (index > -1) {
        this.pending.splice(index, 1);
      }
      this.pending.push(entry);

      this.committing = true;
      this.commitMsg = "";
      this.commitError = "";

      try {
        const data = await api("/api/objects/commit", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ changes: [entry] })
        });

        // Remove the committed entry (by id+op: Alpine stores it in a
        // reactive proxy, so reference comparison would not match).
        const idx = this.pending.findIndex(
          (change) => change.id === entry.id && change.op === entry.op
        );
        if (idx > -1) {
          this.pending.splice(idx, 1);
        }
        this.commitMsg = data.message;
        this.closeModal();
        await this.load();
        setTimeout(() => {
          this.commitMsg = "";
        }, 6000);
      } catch (error) {
        // The change stays staged: retry it (with the other staged changes)
        // from the toolbar Validate button.
        this.commitError = `${error.message} — the change is staged; retry it with the Validate button in the toolbar.`;
        this.closeModal();
      } finally {
        this.committing = false;
      }
    },

    stageDeleteFromRow(row) {
      if (row.is_deleted) {
        return;
      }

      if (this.pendingFor(row.id)) {
        alert("This object already has a staged change. Discard it first.");
        return;
      }

      if (!confirm(`Move "${row.name}" to the trash (staged — commit with Validate)?`)) {
        return;
      }

      this.pending.push({ op: "delete", id: row.id, name: row.name, reason: "Deleted from UI" });
    },

    // Direct restore of a deleted row (POST /api/objects/<id>/restore) —
    // no staging: the row goes back to the active list immediately.
    async restoreRow(row) {
      if (!confirm(`Restore "${row.name}"?`)) {
        return;
      }

      this.committing = true;
      this.commitMsg = "";
      this.commitError = "";

      try {
        await api(`/api/objects/${row.id}/restore`, { method: "POST" });
        this.commitMsg = `Object "${row.name}" restored.`;
        await this.load();
        setTimeout(() => {
          this.commitMsg = "";
        }, 6000);
      } catch (error) {
        this.commitError = error.message;
      } finally {
        this.committing = false;
      }
    },

    openAdd() {
      if (!this.scope.firewall_id) {
        alert(
          "Objects are added per firewall. Open this page from a project or firewall to add objects."
        );
        return;
      }

      const template = PAYLOAD_TEMPLATES[this.scope.object_type] || {};
      this.addName = "";
      this.addDescription = "";
      this.addPayloadText = JSON.stringify(template, null, 2);
      this.addOpen = true;
    },

    closeAdd() {
      this.addOpen = false;
    },

    stageAdd() {
      let payload;

      try {
        payload = JSON.parse(this.addPayloadText);
      } catch (_) {
        alert("Payload must be valid JSON.");
        return;
      }

      if (!this.addName.trim()) {
        alert("Name is required.");
        return;
      }

      this.pending.push({
        op: "create",
        firewall_id: Number(this.scope.firewall_id),
        object_type: this.scope.object_type,
        name: this.addName.trim(),
        description: this.addDescription || null,
        payload
      });

      this.commitMsg = "";
      this.commitError = "";
      this.closeAdd();
    },

    discard() {
      if (!confirm("Discard all staged changes?")) {
        return;
      }
      this.pending = [];
      this.commitMsg = "";
      this.commitError = "";
    },

    // Commit every staged change to the database in one transaction.
    async validate() {
      if (this.pending.length === 0 || this.committing) {
        return;
      }

      this.committing = true;
      this.commitError = "";
      this.commitMsg = "";

      try {
        const data = await api("/api/objects/commit", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ changes: this.pending })
        });

        this.pending = [];
        this.commitMsg = data.message;
        await this.load();
        setTimeout(() => {
          this.commitMsg = "";
        }, 6000);
      } catch (error) {
        this.commitError = error.message;
      } finally {
        this.committing = false;
      }
    }
  };
}


// ---------------------------------------------------------------------------
// Export wizard (4 steps)
// ---------------------------------------------------------------------------

function exportWizard(stats, projectId) {
  const firewalls = (stats && stats.firewalls) || [];
  const types = (stats && stats.types) || OBJECT_TYPES;
  // Per-type counts over ALL firewalls in the database (the export scope):
  // the destination receives every matching object, not only its own.
  const database = (stats && stats.database) || {};
  const preselected = new URLSearchParams(window.location.search).get("firewall_id") || "";

  return {
    stats,
    firewalls,
    backUrl: projectId ? `/projects/${projectId}` : "/",
    step: 1,
    stepError: "",
    fwId: preselected && firewalls.some((fw) => String(fw.id) === preselected)
      ? Number(preselected)
      : firewalls.length
        ? firewalls[0].id
        : "",
    selectedTypes: [],
    typeScope: {}, // per type: "tagged" (default) or "all"
    method: "file",
    format: "xml", // Palo Alto file export: "xml" or "set"
    // Step 4 — file
    fileBusy: false,
    fileProgress: 0,
    fileResult: null,
    fileError: "",
    // Step 4 — push
    connBusy: false,
    connResult: null,
    pushBusy: false,
    pushProgress: 0,
    pushStage: "",
    pushResult: null,
    pushError: "",

    init() {
      // By default the export contains the objects tagged “Include in the
      // export” on the object list page, per object type (counted over all
      // firewalls in the database); types without any tagged object start
      // unselected. “Select all” widens everything to “All objects”
      // (including the not-tagged ones).
      this.selectedTypes = types.filter((t) => this.includedCount(t) > 0);
      for (const t of this.selectedTypes) {
        this.typeScope[t] = "tagged";
      }
    },

    fw() {
      return firewalls.find((fw) => fw.id === this.fwId) || null;
    },

    // The export delivers the whole database configuration to the
    // destination, so these counts span every firewall — not only the
    // destination's own objects.
    typeCount(type) {
      return (database.types && database.types[type]) || 0;
    },

    includedCount(type) {
      return (database.included && database.included[type]) || 0;
    },

    modifiedCount(type) {
      return (database.modified && database.modified[type]) || 0;
    },

    scopeOf(type) {
      return this.typeScope[type] || "tagged";
    },

    setScope(type, scope) {
      this.typeScope[type] = scope;
    },

    effectiveCount(type) {
      return this.scopeOf(type) === "all" ? this.typeCount(type) : this.includedCount(type);
    },

    totalSelected() {
      return this.selectedTypes.reduce((sum, type) => sum + this.effectiveCount(type), 0);
    },

    taggedOnlyTypes() {
      return this.selectedTypes.filter((type) => this.scopeOf(type) === "tagged");
    },

    toggleType(type) {
      const index = this.selectedTypes.indexOf(type);
      if (index > -1) {
        this.selectedTypes.splice(index, 1);
      } else {
        this.selectedTypes.push(type);
        this.typeScope[type] = "tagged";
      }
    },

    selectAllTypes() {
      this.selectedTypes = types.slice();
      for (const t of types) {
        this.typeScope[t] = "all";
      }
    },

    // "Tagged only" shortcut: every object type filter is selected in the
    // "Tagged only" scope, so the export carries only the objects tagged
    // "Include in the export" on the object list page.
    selectTaggedOnly() {
      this.selectedTypes = types.slice();
      for (const t of types) {
        this.typeScope[t] = "tagged";
      }
    },

    clearAllTypes() {
      this.selectedTypes = [];
    },

    formatLabel() {
      const firewall = this.fw();
      if (!firewall) return "—";
      if (firewall.vendor === "paloalto") {
        return this.format === "set" ? "paloalto — set (show) format" : "paloalto — XML";
      }
      return `${firewall.vendor} — native config`;
    },

    next() {
      if (this.step === 1 && !this.fwId) {
        this.stepError = "Select a destination firewall.";
        return;
      }
      if (this.step === 2 && this.selectedTypes.length === 0) {
        this.stepError = "Select at least one object type.";
        return;
      }
      if (this.step === 2 && this.totalSelected() === 0) {
        this.stepError =
          "No objects to export with the current selection — tag objects on the object list "
          + "page (\"Include in the export\") or switch a type to \"All objects\".";
        return;
      }

      this.stepError = "";
      if (this.step < 4) this.step += 1;

      if (this.step === 4 && this.method === "push") {
        this.checkConn();
      }
    },

    back() {
      if (this.step > 1) {
        this.step -= 1;
        this.stepError = "";
      }
    },

    async checkConn() {
      if (!this.fwId) {
        return;
      }

      this.connBusy = true;
      this.connResult = null;

      try {
        this.connResult = await api("/api/connectivity", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ firewall_id: this.fwId })
        });
      } catch (error) {
        this.connResult = { ok: false, detail: error.message };
      } finally {
        this.connBusy = false;
      }
    },

    async generateFile() {
      this.fileBusy = true;
      this.fileError = "";
      this.fileResult = null;
      this.fileProgress = 20;
      this.fileStage = "Generating vendor configuration...";

      try {
        const data = await api("/api/export/file", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            firewall_id: this.fwId,
            object_types: this.selectedTypes,
            tagged_only_types: this.taggedOnlyTypes(),
            format: this.format
          })
        });

        this.fileProgress = 75;
        this.fileStage = "Packaging file...";
        await new Promise((resolve) => setTimeout(resolve, 350));
        this.fileProgress = 100;
        this.fileResult = data;
      } catch (error) {
        this.fileError = error.message;
        this.fileProgress = 0;
      } finally {
        this.fileBusy = false;
      }
    },

    async push() {
      this.pushBusy = true;
      this.pushError = "";
      this.pushResult = null;
      this.pushProgress = 0;
      this.pushStage = "Starting...";

      try {
        const response = await fetch("/api/export/push", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            firewall_id: this.fwId,
            object_types: this.selectedTypes,
            tagged_only_types: this.taggedOnlyTypes()
          })
        });

        if (!response.ok) {
          let message = "Push failed.";
          try {
            const data = await response.json();
            message = data.error || message;
          } catch (_) {
            // Not a JSON body.
          }
          throw new Error(message);
        }

        let failed = null;

        await readNdjson(response, (line) => {
          if (line.event === "progress") {
            this.pushProgress = line.percent;
            this.pushStage = line.detail;
          } else if (line.event === "done") {
            this.pushProgress = 100;
            this.pushResult = line;
          } else if (line.event === "error") {
            failed = new Error(line.error);
          }
        });

        if (failed) throw failed;
      } catch (error) {
        this.pushError = error.message;
      } finally {
        this.pushBusy = false;
      }
    },

    get succeeded() {
      return !!(this.fileResult || this.pushResult);
    }
  };
}


// ---------------------------------------------------------------------------
// Import Wizard (standalone /import page)
// ---------------------------------------------------------------------------

function importWizard(firewalls, projectId) {
  const params = new URLSearchParams(window.location.search);
  const preselectedFirewall = params.get("firewall_id") || "";
  const preselected = preselectedFirewall !== "";

  return {
    firewalls: Array.isArray(firewalls) ? firewalls : [],
    projectId: projectId || null,
    // When a firewall is preselected (e.g. the per-row Import action on the
    // project page), skip straight to the source step.
    step: preselected ? 2 : 1,
    firewall_id: preselectedFirewall,
    source_type: "file",
    url: "",
    types: OBJECT_TYPES.slice(),
    object_types: OBJECT_TYPES.slice(),
    error: "",
    result: null,
    busy: false,
    fileName: "",
    importHistory: [],
    historyLoading: false,

    init() {
      if (this.firewall_id) {
        this.loadHistory();
      }
    },

    firewall() {
      return (
        this.firewalls.find((fw) => String(fw.id) === String(this.firewall_id)) ||
        null
      );
    },

    setFileName(name) {
      this.fileName = name;
    },

    // The page the wizard was opened from: the project page when a project
    // id was passed (per-row Import action), the dashboard otherwise.
    goOrigin() {
      location.href = this.projectId ? `/projects/${this.projectId}` : "/";
    },

    next() {
      if (this.step === 1 && !this.firewall_id) {
        this.error = "Select a firewall before continuing.";
        return;
      }

      if (this.step < 3) {
        this.step += 1;
        this.error = "";
      }
    },

    back() {
      // Step 2 is the first step when a firewall was preselected — Back
      // leaves the wizard for the page it was opened from (project page or
      // dashboard). Otherwise go back one wizard step.
      if (this.step === 2 && preselected) {
        this.goOrigin();
        return;
      }

      if (this.step > 1) {
        this.step -= 1;
        this.error = "";
      }
    },

    selectAllTypes() {
      this.object_types = this.types.slice();
    },

    clearAllTypes() {
      this.object_types = [];
    },

    async loadHistory() {
      if (!this.firewall_id) {
        return;
      }

      this.historyLoading = true;

      try {
        const data = await api(`/api/import/records?firewall_id=${this.firewall_id}`);
        this.importHistory = data.items || [];
      } catch (_) {
        this.importHistory = [];
      } finally {
        this.historyLoading = false;
      }
    },

    onFirewallChange() {
      this.loadHistory();
    },

    toggleType(type) {
      const index = this.object_types.indexOf(type);

      if (index > -1) {
        this.object_types.splice(index, 1);
      } else {
        this.object_types.push(type);
      }
    },

    async submitImport() {
      this.error = "";
      this.result = null;
      this.busy = true;

      try {
        const formData = new FormData();

        formData.append("firewall_id", this.firewall_id);
        formData.append("source_type", this.source_type);
        formData.append("object_types", this.object_types.join(","));

        if (this.source_type === "file") {
          const fileInput = this.$refs.fileInput;
          const file = fileInput ? fileInput.files[0] : null;

          if (!file) {
            this.error = "Choose a configuration file to upload.";
            return;
          }

          formData.append("config_file", file);
        } else {
          if (!this.url.trim()) {
            this.error = "Enter the URL of the configuration file.";
            return;
          }

          formData.append("url", this.url);
        }

        const response = await fetch("/api/import", {
          method: "POST",
          body: formData
        });

        // The API answers JSON; a non-JSON body (e.g. an HTML error page)
        // must not blow up the error message.
        let data = null;

        try {
          data = await response.json();
        } catch (_) {
          // Not a JSON body — keep the HTTP status below.
        }

        if (!response.ok) {
          throw new Error(
            (data && data.error) || `Import failed (HTTP ${response.status}).`
          );
        }

        this.result = data;
        this.loadHistory();
      } catch (error) {
        this.error = error.message;
      } finally {
        this.busy = false;
      }
    }
  };
}


// ---------------------------------------------------------------------------
// Trash Bin — two separate trashes:
// - Dashboard trash (no projectId): deleted projects + firewalls only.
// - Project trash (projectId, the trash can on the project page): that
//   project's deleted objects only.
// ---------------------------------------------------------------------------

function trashBin(projectId) {
  return {
    projectId: projectId || null,
    projects: [],
    firewalls: [],
    items: [],
    search: "",
    // Trash ids selected with the row checkboxes — the permanent-delete
    // buttons act on this selection (project trash can only).
    selected: [],
    loading: true,
    error: "",
    busy: "",

    // Object-trash search: filters the deleted-objects list by name, type,
    // firewall, project or reason (client-side, no server call). A getter —
    // the template reads it as a property; as a method, x-for iterated the
    // function itself (non-iterable) and the table rendered no rows at all.
    get filteredItems() {
      const term = (this.search || "").trim().toLowerCase();

      if (!term) {
        return this.items;
      }

      return this.items.filter((item) => {
        const haystack = [
          item.name,
          item.object_type,
          item.firewall_name,
          item.project_name,
          item.reason
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();

        return haystack.includes(term);
      });
    },

    async init() {
      try {
        const url = this.projectId ? `/api/trash?project_id=${this.projectId}` : "/api/trash";
        const data = await api(url);
        this.projects = data.projects || [];
        this.firewalls = data.firewalls || [];
        // Objects belong to the project trash can only — the dashboard
        // trash lists projects and firewalls.
        this.items = this.projectId ? data.items || [] : [];
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },

    // kind = "project" | "firewall" | "object" — used to disable every
    // Restore button while one restore is in flight.
    async restore(kind, trashId, label) {
      if (!confirm(`Restore ${label}?`)) {
        return;
      }

      this.busy = `${kind}-${trashId}`;

      try {
        await api(`/api/trash/${trashId}/restore`, { method: "POST" });
        location.reload();
      } catch (error) {
        alert(error.message);
        this.busy = "";
      }
    },

    // ── Permanent delete (project trash can only) ──────────────────────
    // Selecting rows with the checkboxes and confirming removes the
    // objects from the database for good (history + trash rows included).

    toggleSelect(trashId) {
      const index = this.selected.indexOf(trashId);

      if (index > -1) {
        this.selected.splice(index, 1);
      } else {
        this.selected.push(trashId);
      }
    },

    // Header checkbox: every row visible in the current search filter.
    get allSelected() {
      return (
        this.filteredItems.length > 0 &&
        this.filteredItems.every((item) => this.selected.includes(item.trash_id))
      );
    },

    toggleAll() {
      if (this.allSelected) {
        const visible = new Set(this.filteredItems.map((item) => item.trash_id));
        this.selected = this.selected.filter((id) => !visible.has(id));
      } else {
        for (const item of this.filteredItems) {
          if (!this.selected.includes(item.trash_id)) {
            this.selected.push(item.trash_id);
          }
        }
      }
    },

    // Permanently delete the selected objects (with confirmation).
    async deleteSelected() {
      const count = this.selected.length;

      if (!count) {
        return;
      }

      if (
        !confirm(
          `Permanently delete ${count} object${count > 1 ? "s" : ""} from the trash? Their modification history goes with them. This cannot be undone.`
        )
      ) {
        return;
      }

      this.busy = "object-perm";

      try {
        await api("/api/trash/permanent-delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ trash_ids: this.selected })
        });
        location.reload();
      } catch (error) {
        alert(error.message);
        this.busy = "";
      }
    },

    // Permanently delete EVERY deleted object of the project (with
    // confirmation — nothing else is touched).
    async deleteAll() {
      const count = this.items.length;

      if (!count) {
        return;
      }

      if (
        !confirm(
          `Permanently delete ALL ${count} objects in the trash of this project? Their modification history goes with them. This cannot be undone.`
        )
      ) {
        return;
      }

      this.busy = "object-perm";

      try {
        await api("/api/trash/permanent-delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ all: true, project_id: this.projectId })
        });
        location.reload();
      } catch (error) {
        alert(error.message);
        this.busy = "";
      }
    }
  };
}
