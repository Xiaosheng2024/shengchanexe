import json
import sqlite3
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


DB_PATH = Path(__file__).with_name("quality_control.db")


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>生产工艺过程质量控制系统 - 管理后台</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: Arial, "Microsoft YaHei", sans-serif; color: #111827; background: #f3f4f6; }
    header { height: 64px; display: flex; align-items: center; padding: 0 24px; background: #111827; color: white; }
    header h1 { font-size: 22px; margin: 0; font-weight: 700; }
    .layout { display: grid; grid-template-columns: 220px 1fr; min-height: calc(100vh - 64px); }
    nav { background: white; border-right: 1px solid #d1d5db; padding: 16px; }
    nav button { width: 100%; display: block; text-align: left; padding: 14px 16px; border: 0; border-radius: 6px; background: transparent; font-size: 17px; cursor: pointer; }
    nav button.active { background: #2563eb; color: white; font-weight: 700; }
    .tree-title { margin: 18px 0 8px; color: #374151; font-weight: 700; }
    .tree-node { padding: 8px 10px; border-radius: 6px; cursor: pointer; font-size: 14px; line-height: 1.3; }
    .tree-node:hover { background: #eff6ff; }
    .tree-node.active { background: #2563eb; color: white; font-weight: 700; }
    .tree-project { margin-top: 6px; }
    .tree-station { margin-left: 14px; }
    .tree-step { margin-left: 28px; color: #4b5563; }
    .tree-step.active { color: white; }
    main { padding: 18px; }
    .page { display: none; }
    .page.active { display: block; }
    .toolbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 14px; }
    .panel { background: white; border: 1px solid #d1d5db; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
    .panel h2 { margin: 0 0 14px; font-size: 20px; }
    label { font-weight: 700; }
    input, select { height: 38px; padding: 6px 10px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 15px; min-width: 160px; }
    button.primary { height: 38px; padding: 0 18px; border: 0; border-radius: 6px; background: #2563eb; color: white; font-size: 15px; font-weight: 700; cursor: pointer; }
    button.secondary { height: 38px; padding: 0 18px; border: 1px solid #cbd5e1; border-radius: 6px; background: white; font-size: 15px; cursor: pointer; }
    button.danger { height: 38px; padding: 0 18px; border: 0; border-radius: 6px; background: #dc2626; color: white; font-size: 15px; cursor: pointer; }
    table { width: 100%; border-collapse: collapse; background: white; }
    th, td { border: 1px solid #e5e7eb; padding: 10px; text-align: left; font-size: 14px; }
    th { background: #f9fafb; }
    .hint { color: #6b7280; font-size: 14px; }
    .status { min-height: 24px; color: #2563eb; font-weight: 700; }
  </style>
</head>
<body>
  <header><h1>生产工艺过程质量控制系统 - 管理后台</h1></header>
  <div class="layout">
    <nav>
      <button class="tab active" data-page="projectPage">项目管理</button>
      <button class="tab" data-page="stationPage">工位管理</button>
      <button class="tab" data-page="stepPage">工序规则管理</button>
      <button class="tab" data-page="recordPage">扫描记录查询</button>
      <div class="tree-title">项目 / 工位 / 规则</div>
      <div id="menuTree"></div>
    </nav>
    <main>
      <div class="status" id="status"></div>

      <section id="projectPage" class="page active">
        <div class="panel">
          <h2>项目管理</h2>
          <div class="toolbar">
            <input id="projectId" type="hidden">
            <label>项目名称</label>
            <input id="projectName" placeholder="例如：X04C中控面板">
            <button class="primary" onclick="addProject()">添加项目</button>
            <button class="primary" onclick="updateProject()">保存修改</button>
            <button class="secondary" onclick="resetProjectForm()">取消编辑</button>
          </div>
          <p class="hint">最大层级：项目。支持新增、修改、删除；删除项目会清理下属工位、工序和记录。</p>
        </div>
        <div class="panel">
          <h2>项目列表 <span class="hint" id="selectedProjectText"></span></h2>
          <table>
            <thead><tr><th>ID</th><th>项目名称</th><th>工位数量</th><th>创建时间</th><th>操作</th></tr></thead>
            <tbody id="projectRows"></tbody>
          </table>
        </div>
      </section>

      <section id="stationPage" class="page">
        <div class="panel">
          <h2>工位管理</h2>
          <div class="toolbar">
            <input id="stationId" type="hidden">
            <label>所属项目</label>
            <select id="stationProject"></select>
            <label>工位名称</label>
            <input id="stationName" placeholder="例如：工位1">
            <button class="primary" onclick="addStation()">添加工位</button>
            <button class="primary" onclick="updateStation()">保存修改</button>
            <button class="secondary" onclick="resetStationForm()">取消编辑</button>
          </div>
          <p class="hint">中间层级：工位。桌面端在线模式会按项目和工位下载对应工序。</p>
        </div>
        <div class="panel">
          <h2>工位列表 <span class="hint" id="selectedStationProjectText"></span></h2>
          <table>
            <thead><tr><th>项目</th><th>工位</th><th>创建时间</th><th>操作</th></tr></thead>
            <tbody id="stationRows"></tbody>
          </table>
        </div>
      </section>

      <section id="stepPage" class="page">
        <div class="panel">
          <h2>工序规则管理</h2>
          <input id="stepId" type="hidden">
          <div class="toolbar">
            <label>项目</label>
            <select id="stepProject" onchange="onStepProjectChanged()"></select>
            <label>工位</label>
            <select id="stepStation" onchange="onStepStationChanged()"></select>
          </div>
          <div class="toolbar">
            <label>工序名称</label>
            <input id="stepName" placeholder="例如：扫码A零件 / 打螺丝10颗">
            <label>功能</label>
            <select id="stepType" onchange="toggleStepFields()">
              <option value="扫码">条码扫描</option>
              <option value="螺丝">螺丝数量</option>
            </select>
            <label>顺序</label>
            <input id="stepOrder" type="number" min="1" value="1">
          </div>
          <div class="toolbar" id="barcodeFields">
            <label>截取起始位</label>
            <input id="barcodeStart" type="number" min="1" value="1">
            <label>截取结束位</label>
            <input id="barcodeEnd" type="number" min="1" value="7">
            <label>检测内容</label>
            <input id="expectedContent" placeholder="为空表示不校验">
          </div>
          <div class="toolbar" id="screwFields" style="display:none">
            <label>螺丝数量</label>
            <input id="requiredCount" type="number" min="1" value="10">
          </div>
          <button class="primary" onclick="addStep()">添加工序规则</button>
          <button class="primary" onclick="updateStep()">保存修改</button>
          <button class="secondary" onclick="resetStepForm()">取消编辑</button>
          <p class="hint">最小层级：工序规则。功能分为条码扫描和螺丝数量；顺序越小越先执行。</p>
        </div>
        <div class="panel">
          <h2>当前工位工序 <span class="hint" id="selectedStationText"></span></h2>
          <button class="secondary" onclick="loadSteps()">刷新工序</button>
          <table>
            <thead><tr><th>顺序</th><th>工序名称</th><th>功能</th><th>螺丝数量</th><th>截取位</th><th>检测内容</th><th>操作</th></tr></thead>
            <tbody id="stepRows"></tbody>
          </table>
        </div>
      </section>

      <section id="recordPage" class="page">
        <div class="panel">
          <h2>扫描记录查询</h2>
          <div class="toolbar">
            <input id="recordId" type="hidden">
            <label>条码</label>
            <input id="recordBarcode" placeholder="支持模糊搜索">
            <label>开始时间</label>
            <input id="recordStart" type="datetime-local">
            <label>结束时间</label>
            <input id="recordEnd" type="datetime-local">
            <button class="primary" onclick="loadRecords()">查询</button>
          </div>
          <div class="toolbar">
            <label>修改条码</label>
            <input id="recordEditBarcode" placeholder="选择记录后修改">
            <label>结果</label>
            <input id="recordEditResult" placeholder="完成 / 扫码错误">
            <label>说明</label>
            <input id="recordEditNote" placeholder="记录说明">
            <button class="primary" onclick="updateRecord()">保存记录修改</button>
            <button class="secondary" onclick="resetRecordForm()">取消编辑</button>
          </div>
          <table>
            <thead><tr><th>时间</th><th>项目</th><th>工位</th><th>条码</th><th>工序</th><th>结果</th><th>说明</th><th>操作</th></tr></thead>
            <tbody id="recordRows"></tbody>
          </table>
        </div>
      </section>
    </main>
  </div>

  <script>
    let fullData = {projects: []};
    let selectedProjectId = null;
    let selectedStationId = null;

    function showStatus(text) {
      document.getElementById("status").textContent = text || "";
      if (text) setTimeout(() => showStatus(""), 3000);
    }

    async function api(path, options = {}) {
      const res = await fetch(path, options);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "请求失败");
      return data;
    }

    function htmlEscape(value) {
      return String(value ?? "").replace(/[&<>"']/g, ch => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }[ch]));
    }

    document.querySelectorAll(".tab").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach(item => item.classList.remove("active"));
        document.querySelectorAll(".page").forEach(item => item.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById(btn.dataset.page).classList.add("active");
      });
    });

    async function refreshAll() {
      fullData = await api("/api/projects/full");
      keepValidSelection();
      renderMenuTree();
      renderProjects();
      renderStations();
      refreshProjectOptions();
      refreshStationOptions();
      loadSteps();
    }

    function keepValidSelection() {
      if (!fullData.projects.length) {
        selectedProjectId = null;
        selectedStationId = null;
        return;
      }
      let project = fullData.projects.find(item => item.id === selectedProjectId);
      if (!project) {
        project = fullData.projects[0];
        selectedProjectId = project.id;
      }
      let station = project.stations.find(item => item.id === selectedStationId);
      if (!station) {
        station = project.stations[0] || null;
        selectedStationId = station ? station.id : null;
      }
    }

    function currentProject() {
      return fullData.projects.find(item => item.id === selectedProjectId) || null;
    }

    function currentStation() {
      const project = currentProject();
      return project ? project.stations.find(item => item.id === selectedStationId) || null : null;
    }

    function setActivePage(pageId) {
      document.querySelectorAll(".tab").forEach(item => item.classList.toggle("active", item.dataset.page === pageId));
      document.querySelectorAll(".page").forEach(item => item.classList.toggle("active", item.id === pageId));
    }

    function selectProject(id) {
      selectedProjectId = id;
      const project = currentProject();
      selectedStationId = project && project.stations[0] ? project.stations[0].id : null;
      resetProjectForm();
      resetStationForm();
      resetStepForm();
      renderMenuTree();
      renderProjects();
      renderStations();
      refreshProjectOptions();
      refreshStationOptions();
      setActivePage("projectPage");
    }

    function selectStation(projectId, stationId) {
      selectedProjectId = projectId;
      selectedStationId = stationId;
      resetStationForm();
      resetStepForm();
      renderMenuTree();
      renderProjects();
      renderStations();
      refreshProjectOptions();
      refreshStationOptions();
      setActivePage("stationPage");
    }

    function selectStep(projectId, stationId, stepId) {
      selectedProjectId = projectId;
      selectedStationId = stationId;
      renderMenuTree();
      refreshProjectOptions();
      refreshStationOptions();
      editStep(stepId);
      setActivePage("stepPage");
    }

    function renderMenuTree() {
      const tree = fullData.projects.map(project => {
        const projectActive = project.id === selectedProjectId;
        const stationHtml = project.stations.map(station => {
          const stationActive = station.id === selectedStationId;
          const steps = station.steps || [];
          const stepHtml = steps.map(step =>
            `<div class="tree-node tree-step" onclick="selectStep(${project.id}, ${station.id}, ${step.id})">规则：${htmlEscape(step.name)}</div>`
          ).join("");
          return `<div class="tree-node tree-station ${stationActive ? "active" : ""}" onclick="selectStation(${project.id}, ${station.id})">工位：${htmlEscape(station.name)}</div>${stationActive ? stepHtml : ""}`;
        }).join("");
        return `<div class="tree-node tree-project ${projectActive ? "active" : ""}" onclick="selectProject(${project.id})">项目：${htmlEscape(project.name)}</div>${projectActive ? stationHtml : ""}`;
      }).join("");
      document.getElementById("menuTree").innerHTML = tree || `<div class="hint">暂无项目</div>`;
      const project = currentProject();
      const station = currentStation();
      document.getElementById("selectedProjectText").textContent = project ? `当前：${project.name}` : "";
      document.getElementById("selectedStationProjectText").textContent = project ? `当前项目：${project.name}` : "";
      document.getElementById("selectedStationText").textContent = station ? `当前：${project.name} / ${station.name}` : "";
    }

    function renderProjects() {
      const rows = fullData.projects.map(project =>
        `<tr><td>${project.id}</td><td>${htmlEscape(project.name)}</td><td>${project.stations.length}</td><td>${project.created_at}</td><td><button class="secondary" onclick="selectProject(${project.id})">选择</button> <button class="secondary" onclick="editProject(${project.id})">编辑</button> <button class="danger" onclick="deleteProject(${project.id})">删除</button></td></tr>`
      ).join("");
      document.getElementById("projectRows").innerHTML = rows || `<tr><td colspan="5">暂无项目</td></tr>`;
    }

    function renderStations() {
      const project = currentProject();
      const rows = (project ? project.stations : []).map(station =>
        `<tr><td>${htmlEscape(project.name)}</td><td>${htmlEscape(station.name)}</td><td>${station.created_at}</td><td><button class="secondary" onclick="selectStation(${project.id}, ${station.id})">选择</button> <button class="secondary" onclick="editStation(${station.id})">编辑</button> <button class="danger" onclick="deleteStation(${station.id})">删除</button></td></tr>`
      ).join("");
      document.getElementById("stationRows").innerHTML = rows || `<tr><td colspan="4">暂无工位</td></tr>`;
    }

    function refreshProjectOptions() {
      ["stationProject", "stepProject"].forEach(id => {
        const select = document.getElementById(id);
        select.innerHTML = fullData.projects.map(project => `<option value="${project.id}">${project.name}</option>`).join("");
        if (selectedProjectId) select.value = selectedProjectId;
      });
    }

    function refreshStationOptions() {
      const projectId = Number(document.getElementById("stepProject").value || selectedProjectId);
      const project = fullData.projects.find(item => item.id === projectId) || fullData.projects[0];
      const select = document.getElementById("stepStation");
      select.innerHTML = project ? project.stations.map(station => `<option value="${station.id}">${station.name}</option>`).join("") : "";
      if (selectedStationId) select.value = selectedStationId;
      loadSteps();
    }

    function onStepProjectChanged() {
      selectedProjectId = Number(document.getElementById("stepProject").value);
      const project = currentProject();
      selectedStationId = project && project.stations[0] ? project.stations[0].id : null;
      renderMenuTree();
      renderStations();
      refreshStationOptions();
    }

    function onStepStationChanged() {
      selectedStationId = Number(document.getElementById("stepStation").value);
      renderMenuTree();
      renderStations();
      loadSteps();
    }

    async function addProject() {
      const name = document.getElementById("projectName").value.trim();
      if (!name) return showStatus("项目名称不能为空");
      await api("/api/projects", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name})
      });
      document.getElementById("projectName").value = "";
      showStatus("项目已添加");
      await refreshAll();
      const project = fullData.projects.find(item => item.name === name);
      if (project) selectProject(project.id);
    }

    function editProject(id) {
      const project = fullData.projects.find(item => item.id === id);
      if (!project) return;
      selectedProjectId = project.id;
      selectedStationId = project.stations[0] ? project.stations[0].id : null;
      document.getElementById("projectId").value = project.id;
      document.getElementById("projectName").value = project.name;
      renderMenuTree();
      renderStations();
      refreshProjectOptions();
      refreshStationOptions();
      showStatus("正在编辑项目");
    }

    function resetProjectForm() {
      document.getElementById("projectId").value = "";
      document.getElementById("projectName").value = "";
    }

    async function updateProject() {
      const id = document.getElementById("projectId").value;
      const name = document.getElementById("projectName").value.trim();
      if (!id) return showStatus("请先在项目列表点击编辑");
      if (!name) return showStatus("项目名称不能为空");
      await api(`/api/projects/${id}`, {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name})
      });
      resetProjectForm();
      showStatus("项目已修改");
      refreshAll();
    }

    async function addStation() {
      const project_id = Number(document.getElementById("stationProject").value || selectedProjectId);
      const name = document.getElementById("stationName").value.trim();
      if (!name) return showStatus("工位名称不能为空");
      await api("/api/stations", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({project_id, name})
      });
      document.getElementById("stationName").value = "";
      showStatus("工位已添加");
      await refreshAll();
      const project = fullData.projects.find(item => item.id === project_id);
      const station = project ? project.stations.find(item => item.name === name) : null;
      if (station) selectStation(project_id, station.id);
    }

    function findStation(id) {
      for (const project of fullData.projects) {
        const station = project.stations.find(item => item.id === id);
        if (station) return {project, station};
      }
      return {};
    }

    function editStation(id) {
      const {project, station} = findStation(id);
      if (!station) return;
      selectedProjectId = project.id;
      selectedStationId = station.id;
      document.getElementById("stationId").value = station.id;
      document.getElementById("stationProject").value = project.id;
      document.getElementById("stationName").value = station.name;
      renderMenuTree();
      renderStations();
      showStatus("正在编辑工位");
    }

    function resetStationForm() {
      document.getElementById("stationId").value = "";
      document.getElementById("stationName").value = "";
    }

    async function updateStation() {
      const id = document.getElementById("stationId").value;
      const project_id = Number(document.getElementById("stationProject").value);
      const name = document.getElementById("stationName").value.trim();
      if (!id) return showStatus("请先在工位列表点击编辑");
      if (!name) return showStatus("工位名称不能为空");
      await api(`/api/stations/${id}`, {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({project_id, name})
      });
      resetStationForm();
      showStatus("工位已修改");
      refreshAll();
    }

    function toggleStepFields() {
      const isScrew = document.getElementById("stepType").value === "螺丝";
      document.getElementById("barcodeFields").style.display = isScrew ? "none" : "flex";
      document.getElementById("screwFields").style.display = isScrew ? "flex" : "none";
    }

    async function addStep() {
      const payload = stepPayload();
      if (!payload.name) return showStatus("工序名称不能为空");
      if (!payload.station_id) return showStatus("请先选择工位");
      await api("/api/steps", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });
      document.getElementById("stepName").value = "";
      showStatus("工序规则已添加");
      refreshAll();
    }

    function stepPayload() {
      const type = document.getElementById("stepType").value;
      return {
        station_id: Number(document.getElementById("stepStation").value || selectedStationId),
        name: document.getElementById("stepName").value.trim(),
        type,
        step_order: Number(document.getElementById("stepOrder").value || 1),
        required_count: type === "螺丝" ? Number(document.getElementById("requiredCount").value || 0) : 0,
        barcode_start: Number(document.getElementById("barcodeStart").value || 1),
        barcode_end: Number(document.getElementById("barcodeEnd").value || 7),
        expected_content: document.getElementById("expectedContent").value.trim()
      };
    }

    function fillStepForm(step) {
      document.getElementById("stepId").value = step.id || "";
      document.getElementById("stepName").value = step.name || "";
      document.getElementById("stepType").value = step.type || "扫码";
      document.getElementById("stepOrder").value = step.step_order || 1;
      document.getElementById("requiredCount").value = step.required_count || 10;
      document.getElementById("barcodeStart").value = step.barcode_start || 1;
      document.getElementById("barcodeEnd").value = step.barcode_end || 7;
      document.getElementById("expectedContent").value = step.expected_content || "";
      toggleStepFields();
    }

    function resetStepForm() {
      fillStepForm({type: "扫码", step_order: 1, required_count: 10, barcode_start: 1, barcode_end: 7});
    }

    async function editStep(id) {
      const stationId = Number(document.getElementById("stepStation").value);
      const data = await api(`/api/stations/${stationId}/steps`);
      const step = data.steps.find(item => item.id === id);
      if (!step) return;
      fillStepForm(step);
      showStatus("正在编辑工序规则");
    }

    async function updateStep() {
      const id = document.getElementById("stepId").value;
      if (!id) return showStatus("请先在工序列表点击编辑");
      const payload = stepPayload();
      if (!payload.name) return showStatus("工序名称不能为空");
      await api(`/api/steps/${id}`, {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });
      resetStepForm();
      showStatus("工序规则已修改");
      refreshAll();
    }

    async function loadSteps() {
      const stationId = Number(document.getElementById("stepStation").value);
      if (!stationId) {
        document.getElementById("stepRows").innerHTML = `<tr><td colspan="7">请选择工位</td></tr>`;
        return;
      }
      const data = await api(`/api/stations/${stationId}/steps`);
      document.getElementById("stepRows").innerHTML = data.steps.map(step =>
        `<tr><td>${step.step_order}</td><td>${htmlEscape(step.name)}</td><td>${step.type}</td><td>${step.required_count || ""}</td><td>${step.barcode_start}-${step.barcode_end}</td><td>${htmlEscape(step.expected_content || "")}</td><td><button class="secondary" onclick="editStep(${step.id})">编辑</button> <button class="danger" onclick="deleteStep(${step.id})">删除</button></td></tr>`
      ).join("") || `<tr><td colspan="7">暂无工序</td></tr>`;
    }

    async function loadRecords() {
      const params = new URLSearchParams();
      const barcode = document.getElementById("recordBarcode").value.trim();
      const start = document.getElementById("recordStart").value;
      const end = document.getElementById("recordEnd").value;
      if (barcode) params.set("barcode", barcode);
      if (start) params.set("start", start);
      if (end) params.set("end", end);
      const data = await api(`/api/scan-records?${params.toString()}`);
      document.getElementById("recordRows").innerHTML = data.records.map(record =>
        `<tr><td>${record.created_at}</td><td>${htmlEscape(record.project)}</td><td>${htmlEscape(record.station)}</td><td>${htmlEscape(record.barcode)}</td><td>${htmlEscape(record.step || "")}</td><td>${htmlEscape(record.result)}</td><td>${htmlEscape(record.note || "")}</td><td><button class="secondary" onclick="editRecord(${record.id})">编辑</button> <button class="danger" onclick="deleteRecord(${record.id})">删除</button></td></tr>`
      ).join("") || `<tr><td colspan="8">暂无记录</td></tr>`;
    }

    async function deleteProject(id) {
      const project = fullData.projects.find(item => item.id === id);
      const name = project ? project.name : id;
      if (!confirm(`确定删除项目“${name}”吗？该项目下的工位、工序和记录也会删除。`)) return;
      await api(`/api/projects/${id}`, {method: "DELETE"});
      showStatus("项目已删除");
      selectedProjectId = null;
      selectedStationId = null;
      refreshAll();
    }

    async function deleteStation(id) {
      const {station} = findStation(id);
      const name = station ? station.name : id;
      if (!confirm(`确定删除工位“${name}”吗？该工位下的工序和记录也会删除。`)) return;
      await api(`/api/stations/${id}`, {method: "DELETE"});
      showStatus("工位已删除");
      selectedStationId = null;
      refreshAll();
    }

    async function deleteStep(id) {
      const stationId = Number(document.getElementById("stepStation").value);
      const data = await api(`/api/stations/${stationId}/steps`);
      const step = data.steps.find(item => item.id === id);
      const name = step ? step.name : id;
      if (!confirm(`确定删除工序“${name}”吗？`)) return;
      await api(`/api/steps/${id}`, {method: "DELETE"});
      showStatus("工序已删除");
      refreshAll();
    }

    function resetRecordForm() {
      document.getElementById("recordId").value = "";
      document.getElementById("recordEditBarcode").value = "";
      document.getElementById("recordEditResult").value = "";
      document.getElementById("recordEditNote").value = "";
    }

    async function editRecord(id) {
      const params = new URLSearchParams();
      params.set("id", id);
      const data = await api(`/api/scan-records?${params.toString()}`);
      const record = data.records[0];
      if (!record) return;
      document.getElementById("recordId").value = record.id;
      document.getElementById("recordEditBarcode").value = record.barcode;
      document.getElementById("recordEditResult").value = record.result;
      document.getElementById("recordEditNote").value = record.note || "";
      showStatus("正在编辑扫描记录");
    }

    async function updateRecord() {
      const id = document.getElementById("recordId").value;
      if (!id) return showStatus("请先在记录列表点击编辑");
      await api(`/api/scan-records/${id}`, {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          barcode: document.getElementById("recordEditBarcode").value.trim(),
          result: document.getElementById("recordEditResult").value.trim(),
          note: document.getElementById("recordEditNote").value.trim()
        })
      });
      resetRecordForm();
      showStatus("扫描记录已修改");
      loadRecords();
    }

    async function deleteRecord(id) {
      if (!confirm("确定删除这条扫描记录吗？")) return;
      await api(`/api/scan-records/${id}`, {method: "DELETE"});
      showStatus("记录已删除");
      loadRecords();
    }

    refreshAll().catch(err => showStatus(err.message));
  </script>
</body>
</html>
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS stations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(project_id, name),
                FOREIGN KEY(project_id) REFERENCES projects(id)
            );
            CREATE TABLE IF NOT EXISTS steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station_id INTEGER NOT NULL,
                step_order INTEGER NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                required_count INTEGER NOT NULL DEFAULT 0,
                barcode_start INTEGER NOT NULL DEFAULT 1,
                barcode_end INTEGER NOT NULL DEFAULT 7,
                expected_content TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(station_id) REFERENCES stations(id)
            );
            CREATE TABLE IF NOT EXISTS station_completions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                station_id INTEGER NOT NULL,
                barcode TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                UNIQUE(project_id, station_id, barcode)
            );
            CREATE TABLE IF NOT EXISTS scan_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                station_id INTEGER,
                barcode TEXT NOT NULL,
                step TEXT,
                result TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        row = conn.execute("SELECT COUNT(*) AS total FROM projects").fetchone()
        if row["total"] == 0:
            seed_default_data(conn)


def now_text():
    return datetime.now().isoformat(timespec="seconds")


def seed_default_data(conn):
    created_at = now_text()
    cursor = conn.execute("INSERT INTO projects (name, created_at) VALUES (?, ?)", ("默认项目", created_at))
    project_id = cursor.lastrowid
    for index in range(1, 10):
        cursor = conn.execute(
            "INSERT INTO stations (project_id, name, created_at) VALUES (?, ?, ?)",
            (project_id, f"工位{index}", created_at),
        )
        station_id = cursor.lastrowid
        default_steps = [
            (1, "扫码A零件", "扫码", 0, 1, 1, "A"),
            (2, "扫码B零件条码", "扫码", 0, 1, 1, "B"),
            (3, "打螺丝10颗", "螺丝", 10, 1, 7, ""),
            (4, "扫码C零件", "扫码", 0, 1, 1, "C"),
        ]
        conn.executemany(
            """
            INSERT INTO steps
            (station_id, step_order, name, type, required_count, barcode_start, barcode_end, expected_content, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(station_id, *step, created_at) for step in default_steps],
        )


def row_to_dict(row):
    return dict(row) if row else None


def json_response(handler, payload, status=200):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def html_response(handler):
    data = HTML.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def read_json(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    if length == 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


class AdminHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        json_response(self, {})

    def do_GET(self):
        try:
            self.route_get()
        except Exception as exc:
            json_response(self, {"error": str(exc)}, 500)

    def do_POST(self):
        try:
            self.route_post()
        except sqlite3.IntegrityError as exc:
            json_response(self, {"error": f"数据重复或不合法：{exc}"}, 400)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, 500)

    def do_PUT(self):
        try:
            self.route_put()
        except sqlite3.IntegrityError as exc:
            json_response(self, {"error": f"数据重复或不合法：{exc}"}, 400)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, 500)

    def do_DELETE(self):
        try:
            self.route_delete()
        except Exception as exc:
            json_response(self, {"error": str(exc)}, 500)

    def route_get(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/":
            html_response(self)
        elif path == "/api/projects":
            json_response(self, {"projects": list_projects()})
        elif path == "/api/projects/full":
            json_response(self, {"projects": list_projects_full()})
        elif path.startswith("/api/projects/") and path.endswith("/config"):
            json_response(self, get_station_config(path))
        elif path.startswith("/api/stations/") and path.endswith("/steps"):
            station_id = int(path.split("/")[3])
            json_response(self, {"steps": list_steps(station_id)})
        elif path == "/api/station-completions/check":
            json_response(self, check_station_completion(query))
        elif path == "/api/scan-records":
            json_response(self, {"records": list_scan_records(query)})
        else:
            json_response(self, {"error": "not found"}, 404)

    def route_post(self):
        path = urlparse(self.path).path
        payload = read_json(self)
        if path == "/api/projects":
            json_response(self, add_project(payload))
        elif path == "/api/stations":
            json_response(self, add_station(payload))
        elif path == "/api/steps":
            json_response(self, add_step(payload))
        elif path == "/api/station-completions":
            json_response(self, add_station_completion(payload))
        elif path == "/api/scan-records":
            json_response(self, add_scan_record(payload))
        else:
            json_response(self, {"error": "not found"}, 404)

    def route_put(self):
        path = urlparse(self.path).path
        payload = read_json(self)
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "projects":
            json_response(self, update_project(int(parts[2]), payload))
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "stations":
            json_response(self, update_station(int(parts[2]), payload))
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "steps":
            json_response(self, update_step(int(parts[2]), payload))
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "scan-records":
            json_response(self, update_scan_record(int(parts[2]), payload))
        else:
            json_response(self, {"error": "not found"}, 404)

    def route_delete(self):
        path = urlparse(self.path).path
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "projects":
            delete_project(int(parts[2]))
            json_response(self, {"ok": True})
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "stations":
            delete_station(int(parts[2]))
            json_response(self, {"ok": True})
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "steps":
            delete_step(int(parts[2]))
            json_response(self, {"ok": True})
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "scan-records":
            delete_scan_record(int(parts[2]))
            json_response(self, {"ok": True})
        else:
            json_response(self, {"error": "not found"}, 404)

    def log_message(self, format, *args):
        return


def list_projects():
    projects = []
    with get_conn() as conn:
        for project in conn.execute("SELECT * FROM projects ORDER BY id"):
            stations = conn.execute(
                "SELECT name FROM stations WHERE project_id = ? ORDER BY id",
                (project["id"],),
            ).fetchall()
            projects.append({"name": project["name"], "stations": [row["name"] for row in stations]})
    return projects


def list_projects_full():
    with get_conn() as conn:
        projects = [row_to_dict(row) for row in conn.execute("SELECT * FROM projects ORDER BY id")]
        for project in projects:
            stations = conn.execute(
                "SELECT * FROM stations WHERE project_id = ? ORDER BY id",
                (project["id"],),
            ).fetchall()
            project["stations"] = [row_to_dict(row) for row in stations]
            for station in project["stations"]:
                station["steps"] = list_steps(station["id"])
    return projects


def add_project(payload):
    name = payload.get("name", "").strip()
    if not name:
        raise ValueError("项目名称不能为空")
    with get_conn() as conn:
        cursor = conn.execute("INSERT INTO projects (name, created_at) VALUES (?, ?)", (name, now_text()))
        return {"id": cursor.lastrowid, "name": name}


def update_project(project_id, payload):
    name = payload.get("name", "").strip()
    if not name:
        raise ValueError("项目名称不能为空")
    with get_conn() as conn:
        conn.execute("UPDATE projects SET name = ? WHERE id = ?", (name, project_id))
    return {"ok": True}


def add_station(payload):
    project_id = int(payload.get("project_id", 0))
    name = payload.get("name", "").strip()
    if not project_id or not name:
        raise ValueError("项目和工位名称不能为空")
    with get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO stations (project_id, name, created_at) VALUES (?, ?, ?)",
            (project_id, name, now_text()),
        )
        return {"id": cursor.lastrowid, "name": name}


def update_station(station_id, payload):
    project_id = int(payload.get("project_id", 0))
    name = payload.get("name", "").strip()
    if not project_id or not name:
        raise ValueError("项目和工位名称不能为空")
    with get_conn() as conn:
        conn.execute(
            "UPDATE stations SET project_id = ?, name = ? WHERE id = ?",
            (project_id, name, station_id),
        )
    return {"ok": True}


def delete_project(project_id):
    with get_conn() as conn:
        station_rows = conn.execute("SELECT id FROM stations WHERE project_id = ?", (project_id,)).fetchall()
        station_ids = [row["id"] for row in station_rows]
        for station_id in station_ids:
            delete_station_with_conn(conn, station_id)
        conn.execute("DELETE FROM scan_records WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM station_completions WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))


def delete_station(station_id):
    with get_conn() as conn:
        delete_station_with_conn(conn, station_id)


def delete_station_with_conn(conn, station_id):
    conn.execute("DELETE FROM steps WHERE station_id = ?", (station_id,))
    conn.execute("DELETE FROM scan_records WHERE station_id = ?", (station_id,))
    conn.execute("DELETE FROM station_completions WHERE station_id = ?", (station_id,))
    conn.execute("DELETE FROM stations WHERE id = ?", (station_id,))


def delete_step(step_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM steps WHERE id = ?", (step_id,))


def add_step(payload):
    station_id = int(payload.get("station_id", 0))
    name = payload.get("name", "").strip()
    step_type = payload.get("type", "扫码")
    if not station_id or not name:
        raise ValueError("工位和工序名称不能为空")
    if step_type not in ("扫码", "螺丝"):
        raise ValueError("功能只能是扫码或螺丝")
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO steps
            (station_id, step_order, name, type, required_count, barcode_start, barcode_end, expected_content, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                station_id,
                int(payload.get("step_order", 1)),
                name,
                step_type,
                int(payload.get("required_count", 0)),
                int(payload.get("barcode_start", 1)),
                int(payload.get("barcode_end", 7)),
                payload.get("expected_content", ""),
                now_text(),
            ),
        )
        return {"id": cursor.lastrowid}


def update_step(step_id, payload):
    name = payload.get("name", "").strip()
    step_type = payload.get("type", "扫码")
    station_id = int(payload.get("station_id", 0))
    if not station_id or not name:
        raise ValueError("工位和工序名称不能为空")
    if step_type not in ("扫码", "螺丝"):
        raise ValueError("功能只能是扫码或螺丝")
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE steps
            SET station_id = ?, step_order = ?, name = ?, type = ?, required_count = ?,
                barcode_start = ?, barcode_end = ?, expected_content = ?
            WHERE id = ?
            """,
            (
                station_id,
                int(payload.get("step_order", 1)),
                name,
                step_type,
                int(payload.get("required_count", 0)),
                int(payload.get("barcode_start", 1)),
                int(payload.get("barcode_end", 7)),
                payload.get("expected_content", ""),
                step_id,
            ),
        )
    return {"ok": True}


def list_steps(station_id):
    with get_conn() as conn:
        return [
            row_to_dict(row)
            for row in conn.execute(
                "SELECT * FROM steps WHERE station_id = ? ORDER BY step_order, id",
                (station_id,),
            )
        ]


def get_station_config(path):
    parts = path.split("/")
    project_name = unquote(parts[3])
    station_name = unquote(parts[5])
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT stations.id AS station_id, projects.name AS project_name, stations.name AS station_name
            FROM stations
            JOIN projects ON projects.id = stations.project_id
            WHERE projects.name = ? AND stations.name = ?
            """,
            (project_name, station_name),
        ).fetchone()
        if not row:
            raise ValueError("未找到项目工位配置")
        steps = list_steps(row["station_id"])
    return {
        "product_name": f"{project_name} - {station_name}",
        "steps": [
            {
                "name": step["name"],
                "type": step["type"],
                "required_count": step["required_count"],
                "barcode_start": step["barcode_start"],
                "barcode_end": step["barcode_end"],
                "expected_content": step["expected_content"],
            }
            for step in steps
        ],
    }


def find_project_station(conn, project_name, station_name):
    return conn.execute(
        """
        SELECT projects.id AS project_id, stations.id AS station_id
        FROM stations
        JOIN projects ON projects.id = stations.project_id
        WHERE projects.name = ? AND stations.name = ?
        """,
        (project_name, station_name),
    ).fetchone()


def check_station_completion(query):
    project = query.get("project", [""])[0]
    barcode = query.get("barcode", [""])[0]
    previous_station = query.get("previous_station", [""])[0]
    with get_conn() as conn:
        ids = find_project_station(conn, project, previous_station)
        if not ids:
            return {"completed": False}
        row = conn.execute(
            """
            SELECT 1 FROM station_completions
            WHERE project_id = ? AND station_id = ? AND barcode = ?
            """,
            (ids["project_id"], ids["station_id"], barcode),
        ).fetchone()
    return {"completed": row is not None}


def add_station_completion(payload):
    project = payload.get("project", "")
    station = payload.get("station", "")
    barcode = payload.get("barcode", "")
    completed_at = payload.get("completed_at") or now_text()
    if not project or not station or not barcode:
        raise ValueError("项目、工位、条码不能为空")
    with get_conn() as conn:
        ids = find_project_station(conn, project, station)
        if not ids:
            raise ValueError("项目或工位不存在")
        conn.execute(
            """
            INSERT OR REPLACE INTO station_completions
            (project_id, station_id, barcode, completed_at)
            VALUES (?, ?, ?, ?)
            """,
            (ids["project_id"], ids["station_id"], barcode, completed_at),
        )
        conn.execute(
            """
            INSERT INTO scan_records
            (project_id, station_id, barcode, step, result, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (ids["project_id"], ids["station_id"], barcode, "工位完成", "完成", "桌面端上报", completed_at),
        )
    return {"ok": True}


def add_scan_record(payload):
    project = payload.get("project", "")
    station = payload.get("station", "")
    barcode = payload.get("barcode", "")
    if not barcode:
        raise ValueError("条码不能为空")
    with get_conn() as conn:
        ids = find_project_station(conn, project, station) if project and station else None
        conn.execute(
            """
            INSERT INTO scan_records
            (project_id, station_id, barcode, step, result, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ids["project_id"] if ids else None,
                ids["station_id"] if ids else None,
                barcode,
                payload.get("step", ""),
                payload.get("result", "记录"),
                payload.get("note", ""),
                payload.get("created_at") or now_text(),
            ),
        )
    return {"ok": True}


def update_scan_record(record_id, payload):
    barcode = payload.get("barcode", "").strip()
    result = payload.get("result", "").strip()
    note = payload.get("note", "")
    if not barcode:
        raise ValueError("条码不能为空")
    if not result:
        raise ValueError("结果不能为空")
    with get_conn() as conn:
        conn.execute(
            "UPDATE scan_records SET barcode = ?, result = ?, note = ? WHERE id = ?",
            (barcode, result, note, record_id),
        )
    return {"ok": True}


def delete_scan_record(record_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM scan_records WHERE id = ?", (record_id,))


def list_scan_records(query):
    record_id = query.get("id", [""])[0]
    barcode = query.get("barcode", [""])[0]
    start = query.get("start", [""])[0]
    end = query.get("end", [""])[0]
    sql = """
        SELECT scan_records.*, projects.name AS project, stations.name AS station
        FROM scan_records
        LEFT JOIN projects ON projects.id = scan_records.project_id
        LEFT JOIN stations ON stations.id = scan_records.station_id
        WHERE 1=1
    """
    params = []
    if record_id:
        sql += " AND scan_records.id = ?"
        params.append(record_id)
    if barcode:
        sql += " AND scan_records.barcode LIKE ?"
        params.append(f"%{barcode}%")
    if start:
        sql += " AND scan_records.created_at >= ?"
        params.append(start)
    if end:
        sql += " AND scan_records.created_at <= ?"
        params.append(end)
    sql += " ORDER BY scan_records.created_at DESC LIMIT 500"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "project": row["project"] or "",
            "station": row["station"] or "",
            "barcode": row["barcode"],
            "step": row["step"],
            "result": row["result"],
            "note": row["note"],
        }
        for row in rows
    ]


def run(host="0.0.0.0", port=8000):
    init_db()
    server = ThreadingHTTPServer((host, port), AdminHandler)
    print(f"管理后台已启动：http://127.0.0.1:{port}")
    print(f"数据库文件：{DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    run()
