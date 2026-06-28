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
    .tree-node { display: flex; align-items: center; gap: 6px; padding: 8px 10px; border-radius: 6px; cursor: pointer; font-size: 14px; line-height: 1.3; }
    .tree-node:hover { background: #eff6ff; }
    .tree-node.active { background: #2563eb; color: white; font-weight: 700; }
    .tree-toggle { display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border: 1px solid #9ca3af; border-radius: 3px; background: white; color: #111827; font-weight: 700; font-family: monospace; flex: 0 0 18px; }
    .tree-spacer { width: 18px; flex: 0 0 18px; }
    .tree-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
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
    input[type="checkbox"] { width: 18px; height: 18px; min-width: 18px; padding: 0; }
    .checkbox-label { display: inline-flex; align-items: center; gap: 8px; height: 38px; }
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
      <button class="tab" data-page="maintenancePage">系统维护</button>
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
              <option value="PLC接收">PLC接收</option>
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
            <label class="checkbox-label"><input id="isMainBarcode" type="checkbox"> 是否主条码</label>
          </div>
          <div class="toolbar" id="screwFields" style="display:none">
            <label>螺丝数量</label>
            <input id="requiredCount" type="number" min="1" value="10">
          </div>
          <div id="plcFields" style="display:none">
            <div class="toolbar">
              <label>PLC IP</label><input id="plcIp" value="10.162.86.65">
              <label>Rack</label><input id="plcRack" type="number" value="0">
              <label>Slot</label><input id="plcSlot" type="number" value="1">
              <label class="checkbox-label"><input id="plcIsMainBarcode" type="checkbox" checked> 是否主条码</label>
            </div>
            <div class="toolbar">
              <label>主条码 DB</label><input id="plcBarcode1Db" type="number" value="201">
              <label>Offset</label><input id="plcBarcode1Offset" type="number" value="800">
              <label>Length</label><input id="plcBarcode1Length" type="number" value="40">
              <input id="plcBarcode2Db" type="hidden" value="201">
              <input id="plcBarcode2Offset" type="hidden" value="840">
              <input id="plcBarcode2Length" type="hidden" value="40">
            </div>
            <div class="toolbar">
              <label>PARTS_OK DB</label><input id="plcPartsOkDb" type="number" value="221">
              <label>Offset</label><input id="plcPartsOkOffset" type="number" value="358">
              <label>类型</label><input id="plcPartsOkType" value="int">
              <label>触发模式</label><input id="plcTriggerMode" value="barcode_changed_then_parts_ok_increment">
            </div>
            <div class="toolbar">
              <input id="plcUseBarcodeIndex" type="hidden" min="1" max="2" value="1">
              <label>编码</label><input id="plcBarcodeEncoding" value="ascii">
              <label>轮询ms</label><input id="plcPollIntervalMs" type="number" value="500">
              <label>超时秒</label><input id="plcTimeoutSeconds" type="number" value="3">
              <label>等待OK秒</label><input id="plcBarcodeWaitOkTimeoutSeconds" type="number" value="30">
            </div>
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
            <thead><tr><th>顺序</th><th>工序名称</th><th>功能</th><th>螺丝数量</th><th>截取位</th><th>检测内容</th><th>主条码</th><th>操作</th></tr></thead>
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

      <section id="maintenancePage" class="page">
        <div class="panel">
          <h2>系统维护 / 数据维护</h2>
          <div class="toolbar">
            <button class="primary" onclick="loadDbStatus()">查看数据库状态</button>
            <button class="secondary" onclick="backupDb()">一键备份数据库</button>
            <label>日期前</label>
            <input id="maintBeforeDate" type="date">
            <label>管理员密码</label>
            <input id="maintPassword" type="password" placeholder="0000">
            <button class="secondary" onclick="archiveOldRecords()">归档历史数据</button>
            <button class="danger" onclick="deleteOldRecords()">删除历史数据</button>
          </div>
          <p class="hint">默认不删除 station_completions；它用于前后工位校验。删除前系统会先自动备份。</p>
          <pre id="dbStatusText" style="white-space:pre-wrap;background:#f9fafb;border:1px solid #e5e7eb;padding:12px;border-radius:6px;"></pre>
        </div>
        <div class="panel">
          <h2>在线工位占用</h2>
          <button class="secondary" onclick="loadStationSessions()">刷新在线工位</button>
          <table>
            <thead><tr><th>项目</th><th>工位</th><th>client_id</th><th>computer_name</th><th>ip_address</th><th>last_heartbeat_at</th><th>状态</th><th>备注</th><th>操作</th></tr></thead>
            <tbody id="stationSessionRows"></tbody>
          </table>
        </div>
        <div class="panel">
          <h2>维护日志</h2>
          <button class="secondary" onclick="loadMaintenanceLogs()">刷新日志</button>
          <table>
            <thead><tr><th>时间</th><th>动作</th><th>消息</th><th>详情</th></tr></thead>
            <tbody id="maintenanceLogRows"></tbody>
          </table>
        </div>
        <div class="panel">
          <h2>客户端版本管理</h2>
          <div class="toolbar">
            <input id="releaseVersion" placeholder="版本号，如 v0.8.5">
            <input id="releaseTitle" placeholder="标题">
            <input id="releaseDate" type="datetime-local">
            <label class="checkbox-label"><input id="releaseStable" type="checkbox" checked> 稳定版</label>
            <label class="checkbox-label"><input id="releaseForceUpdate" type="checkbox"> 强制更新</label>
          </div>
          <div class="toolbar">
            <input id="releaseMinVersion" placeholder="最低可用版本">
            <input id="releaseNotes" placeholder="更新说明，多条用 | 分隔" style="min-width:320px; flex:1">
          </div>
          <div class="toolbar">
            <label>正式版文件</label><input id="releaseFile" type="file" accept=".exe,.zip">
            <label>Debug版文件</label><input id="debugFile" type="file" accept=".exe,.zip">
            <label>S7工具</label><input id="s7ToolFile" type="file" accept=".exe,.zip">
            <button class="primary" onclick="saveClientRelease()">保存版本</button>
            <button class="secondary" onclick="refreshClientReleases()">刷新版本</button>
          </div>
          <table>
            <thead><tr><th>版本</th><th>标题</th><th>发布时间</th><th>稳定</th><th>强制</th><th>说明</th><th>操作</th></tr></thead>
            <tbody id="clientReleaseRows"></tbody>
          </table>
        </div>
        <div class="panel">
          <h2>客户端更新日志</h2>
          <button class="secondary" onclick="refreshClientUpdateLogs()">刷新日志</button>
          <table>
            <thead><tr><th>时间</th><th>client_id</th><th>电脑</th><th>当前版本</th><th>目标版本</th><th>动作</th><th>结果</th><th>消息</th></tr></thead>
            <tbody id="clientUpdateLogRows"></tbody>
          </table>
        </div>
      </section>
    </main>
  </div>

  <script>
    let fullData = {projects: []};
    let selectedProjectId = null;
    let selectedStationId = null;
    const expandedProjects = new Set();
    const expandedStations = new Set();

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
      expandedProjects.add(selectedProjectId);
      let station = project.stations.find(item => item.id === selectedStationId);
      if (!station) {
        station = project.stations[0] || null;
        selectedStationId = station ? station.id : null;
      }
      if (selectedStationId) expandedStations.add(selectedStationId);
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
      expandedProjects.add(id);
      const project = currentProject();
      selectedStationId = project && project.stations[0] ? project.stations[0].id : null;
      if (selectedStationId) expandedStations.add(selectedStationId);
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
      expandedProjects.add(projectId);
      expandedStations.add(stationId);
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
      expandedProjects.add(projectId);
      expandedStations.add(stationId);
      renderMenuTree();
      refreshProjectOptions();
      refreshStationOptions();
      editStep(stepId);
      setActivePage("stepPage");
    }

    function toggleProject(event, projectId) {
      event.stopPropagation();
      if (expandedProjects.has(projectId)) expandedProjects.delete(projectId);
      else expandedProjects.add(projectId);
      renderMenuTree();
    }

    function toggleStation(event, projectId, stationId) {
      event.stopPropagation();
      expandedProjects.add(projectId);
      if (expandedStations.has(stationId)) expandedStations.delete(stationId);
      else expandedStations.add(stationId);
      renderMenuTree();
    }

    function renderMenuTree() {
      const tree = fullData.projects.map(project => {
        const projectActive = project.id === selectedProjectId;
        const projectExpanded = expandedProjects.has(project.id);
        const projectSign = projectExpanded ? "-" : "+";
        const stationHtml = project.stations.map(station => {
          const stationActive = station.id === selectedStationId;
          const stationExpanded = expandedStations.has(station.id);
          const stationSign = stationExpanded ? "-" : "+";
          const steps = station.steps || [];
          const stepHtml = steps.map(step =>
            `<div class="tree-node tree-step" onclick="selectStep(${project.id}, ${station.id}, ${step.id})"><span class="tree-spacer"></span><span class="tree-label">规则：${htmlEscape(step.name)}</span></div>`
          ).join("");
          return `<div class="tree-node tree-station ${stationActive ? "active" : ""}" onclick="selectStation(${project.id}, ${station.id})"><span class="tree-toggle" onclick="toggleStation(event, ${project.id}, ${station.id})">${stationSign}</span><span class="tree-label">工位：${htmlEscape(station.name)}</span></div>${stationExpanded ? stepHtml : ""}`;
        }).join("");
        return `<div class="tree-node tree-project ${projectActive ? "active" : ""}" onclick="selectProject(${project.id})"><span class="tree-toggle" onclick="toggleProject(event, ${project.id})">${projectSign}</span><span class="tree-label">项目：${htmlEscape(project.name)}</span></div>${projectExpanded ? stationHtml : ""}`;
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
      if (project) {
        expandedProjects.add(project.id);
        selectProject(project.id);
      }
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
      if (station) {
        expandedProjects.add(project_id);
        expandedStations.add(station.id);
        selectStation(project_id, station.id);
      }
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
      const type = document.getElementById("stepType").value;
      const isScrew = type === "螺丝";
      const isPlc = type === "PLC接收";
      document.getElementById("barcodeFields").style.display = (!isScrew && !isPlc) ? "flex" : "none";
      document.getElementById("screwFields").style.display = isScrew ? "flex" : "none";
      document.getElementById("plcFields").style.display = isPlc ? "block" : "none";
      const mainBarcode = document.getElementById("isMainBarcode");
      mainBarcode.disabled = isScrew;
      if (isScrew) mainBarcode.checked = false;
    }

    async function addStep() {
      const payload = stepPayload();
      if (!payload.name) return showStatus("工序名称不能为空");
      if (!payload.station_id) return showStatus("请先选择工位");
      try {
        await api("/api/steps", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload)
        });
      } catch (err) {
        return showStatus(err.message);
      }
      document.getElementById("stepName").value = "";
      showStatus("工序规则已添加");
      expandedStations.add(payload.station_id);
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
        expected_content: document.getElementById("expectedContent").value.trim(),
        is_main_barcode: (type === "PLC接收" && document.getElementById("plcIsMainBarcode").checked) || (type === "扫码" && document.getElementById("isMainBarcode").checked),
        plc_ip: document.getElementById("plcIp").value.trim(),
        plc_rack: Number(document.getElementById("plcRack").value || 0),
        plc_slot: Number(document.getElementById("plcSlot").value || 1),
        plc_barcode_db: Number(document.getElementById("plcBarcode1Db").value || 201),
        plc_barcode_offset: Number(document.getElementById("plcBarcode1Offset").value || 800),
        plc_barcode_length: Number(document.getElementById("plcBarcode1Length").value || 40),
        plc_barcode1_db: Number(document.getElementById("plcBarcode1Db").value || 201),
        plc_barcode1_offset: Number(document.getElementById("plcBarcode1Offset").value || 800),
        plc_barcode1_length: Number(document.getElementById("plcBarcode1Length").value || 40),
        plc_barcode2_db: Number(document.getElementById("plcBarcode2Db").value || 201),
        plc_barcode2_offset: Number(document.getElementById("plcBarcode2Offset").value || 840),
        plc_barcode2_length: Number(document.getElementById("plcBarcode2Length").value || 40),
        plc_parts_ok_db: Number(document.getElementById("plcPartsOkDb").value || 221),
        plc_parts_ok_offset: Number(document.getElementById("plcPartsOkOffset").value || 358),
        plc_parts_ok_type: document.getElementById("plcPartsOkType").value || "int",
        plc_trigger_mode: document.getElementById("plcTriggerMode").value || "barcode_changed_then_parts_ok_increment",
        plc_use_barcode_index: Number(document.getElementById("plcUseBarcodeIndex").value || 1),
        plc_barcode_encoding: document.getElementById("plcBarcodeEncoding").value || "ascii",
        plc_barcode_strip_null: true,
        plc_barcode_strip_space: true,
        plc_timeout_seconds: Number(document.getElementById("plcTimeoutSeconds").value || 3),
        plc_poll_interval_ms: Number(document.getElementById("plcPollIntervalMs").value || 500),
        plc_barcode_wait_ok_timeout_seconds: Number(document.getElementById("plcBarcodeWaitOkTimeoutSeconds").value || 30)
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
      document.getElementById("isMainBarcode").checked = !!step.is_main_barcode;
      document.getElementById("plcIsMainBarcode").checked = !!step.is_main_barcode;
      document.getElementById("plcIp").value = step.plc_ip || "10.162.86.65";
      document.getElementById("plcRack").value = step.plc_rack ?? 0;
      document.getElementById("plcSlot").value = step.plc_slot ?? 1;
      document.getElementById("plcBarcode1Db").value = step.plc_barcode_db ?? step.plc_barcode1_db ?? 201;
      document.getElementById("plcBarcode1Offset").value = step.plc_barcode_offset ?? step.plc_barcode1_offset ?? 800;
      document.getElementById("plcBarcode1Length").value = step.plc_barcode_length ?? step.plc_barcode1_length ?? 40;
      document.getElementById("plcBarcode2Db").value = step.plc_barcode2_db ?? 201;
      document.getElementById("plcBarcode2Offset").value = step.plc_barcode2_offset ?? 840;
      document.getElementById("plcBarcode2Length").value = step.plc_barcode2_length ?? 40;
      document.getElementById("plcPartsOkDb").value = step.plc_parts_ok_db ?? 221;
      document.getElementById("plcPartsOkOffset").value = step.plc_parts_ok_offset ?? 358;
      document.getElementById("plcPartsOkType").value = step.plc_parts_ok_type || "int";
      document.getElementById("plcTriggerMode").value = step.plc_trigger_mode || "barcode_changed_then_parts_ok_increment";
      document.getElementById("plcUseBarcodeIndex").value = step.plc_use_barcode_index ?? 1;
      document.getElementById("plcBarcodeEncoding").value = step.plc_barcode_encoding || "ascii";
      document.getElementById("plcPollIntervalMs").value = step.plc_poll_interval_ms ?? 500;
      document.getElementById("plcTimeoutSeconds").value = step.plc_timeout_seconds ?? 3;
      document.getElementById("plcBarcodeWaitOkTimeoutSeconds").value = step.plc_barcode_wait_ok_timeout_seconds ?? 30;
      toggleStepFields();
    }

    function resetStepForm() {
      fillStepForm({type: "扫码", step_order: 1, required_count: 10, barcode_start: 1, barcode_end: 7, is_main_barcode: false});
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
      try {
        await api(`/api/steps/${id}`, {
          method: "PUT",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload)
        });
      } catch (err) {
        return showStatus(err.message);
      }
      resetStepForm();
      showStatus("工序规则已修改");
      expandedStations.add(payload.station_id);
      refreshAll();
    }

    async function loadSteps() {
      const stationId = Number(document.getElementById("stepStation").value);
      if (!stationId) {
        document.getElementById("stepRows").innerHTML = `<tr><td colspan="8">请选择工位</td></tr>`;
        return;
      }
      const data = await api(`/api/stations/${stationId}/steps`);
      document.getElementById("stepRows").innerHTML = data.steps.map(step =>
        `<tr><td>${step.step_order}</td><td>${htmlEscape(step.name)}</td><td>${step.type}</td><td>${step.required_count || ""}</td><td>${step.barcode_start}-${step.barcode_end}</td><td>${htmlEscape(step.expected_content || "")}</td><td>${step.is_main_barcode ? "是" : "否"}</td><td><button class="secondary" onclick="editStep(${step.id})">编辑</button> <button class="danger" onclick="deleteStep(${step.id})">删除</button></td></tr>`
      ).join("") || `<tr><td colspan="8">暂无工序</td></tr>`;
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
      try {
        await api(`/api/steps/${id}`, {method: "DELETE"});
      } catch (err) {
        return showStatus(err.message);
      }
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

    async function loadDbStatus() {
      const data = await api("/api/admin/db/status");
      document.getElementById("dbStatusText").textContent = JSON.stringify(data, null, 2);
      await loadStationSessions();
      await loadMaintenanceLogs();
    }

    async function backupDb() {
      const data = await api("/api/admin/db/backup", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"});
      showStatus(`备份完成：${data.backup_file}`);
      await loadMaintenanceLogs();
    }

    async function archiveOldRecords() {
      const before_date = document.getElementById("maintBeforeDate").value;
      if (!before_date) return showStatus("请选择日期");
      const data = await api("/api/admin/db/archive", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({before_date})
      });
      showStatus(`归档完成：${data.archive_file}`);
      await loadMaintenanceLogs();
    }

    async function deleteOldRecords() {
      const before_date = document.getElementById("maintBeforeDate").value;
      const admin_password = document.getElementById("maintPassword").value;
      if (!before_date) return showStatus("请选择日期");
      if (!admin_password) return showStatus("请输入管理员密码");
      if (!confirm(`确定删除 ${before_date} 之前的历史数据吗？系统会先自动备份。`)) return;
      const data = await api("/api/admin/db/delete-old-records", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          before_date,
          admin_password,
          tables: ["scan_records", "station_work_records", "step_work_records", "screw_action_records", "station_session_logs"],
          include_station_completions: false
        })
      });
      showStatus(data.message || "删除完成");
      await loadMaintenanceLogs();
    }

    async function loadMaintenanceLogs() {
      const data = await api("/api/admin/db/maintenance-logs?page=1&page_size=100");
      document.getElementById("maintenanceLogRows").innerHTML = data.records.map(row =>
        `<tr><td>${row.created_at}</td><td>${htmlEscape(row.action)}</td><td>${htmlEscape(row.message || "")}</td><td>${htmlEscape(row.detail || "")}</td></tr>`
      ).join("") || `<tr><td colspan="4">暂无日志</td></tr>`;
    }

    async function refreshClientReleases() {
      const data = await api("/api/client-releases");
      document.getElementById("clientReleaseRows").innerHTML = data.releases.map(row =>
        `<tr><td>${htmlEscape(row.version)}</td><td>${htmlEscape(row.title || "")}</td><td>${htmlEscape(row.release_date || "")}</td><td>${row.stable ? "是" : "否"}</td><td>${row.force_update ? "是" : "否"}</td><td>${htmlEscape((row.release_notes || []).join(" | "))}</td><td><button class="secondary" onclick="downloadClientRelease('${htmlEscape(row.version)}','release')">下载正式版</button> <button class="secondary" onclick="downloadClientRelease('${htmlEscape(row.version)}','debug')">下载Debug版</button> <button class="danger" onclick="deleteClientRelease('${htmlEscape(row.version)}')">删除</button></td></tr>`
      ).join("") || `<tr><td colspan="7">暂无版本</td></tr>`;
    }

    async function refreshClientUpdateLogs() {
      const data = await api("/api/client-update/logs?page=1&page_size=100");
      document.getElementById("clientUpdateLogRows").innerHTML = data.records.map(row =>
        `<tr><td>${htmlEscape(row.created_at || "")}</td><td>${htmlEscape(row.client_id || "")}</td><td>${htmlEscape(row.computer_name || "")}</td><td>${htmlEscape(row.current_version || "")}</td><td>${htmlEscape(row.target_version || "")}</td><td>${htmlEscape(row.action || "")}</td><td>${htmlEscape(row.result || "")}</td><td>${htmlEscape(row.message || "")}</td></tr>`
      ).join("") || `<tr><td colspan="8">暂无日志</td></tr>`;
    }

    function readFileInput(id) {
      const input = document.getElementById(id);
      return input && input.files && input.files[0] ? input.files[0] : null;
    }

    async function saveClientRelease() {
      const version = document.getElementById("releaseVersion").value.trim();
      if (!version) return showStatus("版本号不能为空");
      const form = new FormData();
      form.append("version", version);
      form.append("title", document.getElementById("releaseTitle").value.trim());
      form.append("release_date", document.getElementById("releaseDate").value || "");
      form.append("stable", document.getElementById("releaseStable").checked ? "1" : "0");
      form.append("force_update", document.getElementById("releaseForceUpdate").checked ? "1" : "0");
      form.append("min_required_version", document.getElementById("releaseMinVersion").value.trim());
      form.append("release_notes", JSON.stringify(
        document.getElementById("releaseNotes").value.split("|").map(item => item.trim()).filter(Boolean)
      ));
      const releaseFile = readFileInput("releaseFile");
      const debugFile = readFileInput("debugFile");
      const s7ToolFile = readFileInput("s7ToolFile");
      if (releaseFile) form.append("release_file", releaseFile);
      if (debugFile) form.append("debug_file", debugFile);
      if (s7ToolFile) form.append("s7_tool_file", s7ToolFile);
      const res = await fetch("/api/client-releases", {method:"POST", body: form});
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "保存失败");
      showStatus("版本已保存");
      await refreshClientReleases();
    }

    async function deleteClientRelease(version) {
      if (!confirm(`确定删除版本 ${version} 吗？`)) return;
      await api(`/api/client-releases/${encodeURIComponent(version)}`, {method: "DELETE"});
      showStatus("版本已删除");
      refreshClientReleases();
    }

    async function downloadClientRelease(version, kind) {
      window.open(`/api/client-update/download/${encodeURIComponent(version)}/${kind}`, "_blank");
    }

    async function loadStationSessions() {
      const data = await api("/api/station-sessions?status=online");
      document.getElementById("stationSessionRows").innerHTML = data.sessions.map(row =>
        `<tr><td>${htmlEscape(row.project_name || "")}</td><td>${htmlEscape(row.station_name || "")}</td><td>${htmlEscape(row.client_id || "")}</td><td>${htmlEscape(row.computer_name || "")}</td><td>${htmlEscape(row.ip_address || "")}</td><td>${htmlEscape(row.last_heartbeat_at || "")}</td><td>${htmlEscape(row.status || "")}</td><td>${htmlEscape(row.note || "")}</td><td><button class="danger" onclick="adminReleaseStationSession(${row.id})">释放工位</button></td></tr>`
      ).join("") || `<tr><td colspan="9">暂无在线工位</td></tr>`;
    }

    async function adminReleaseStationSession(sessionId) {
      const admin_password = prompt("请输入管理员密码");
      if (!admin_password) return;
      if (!confirm("确定释放这个在线工位吗？")) return;
      await api("/api/station-session/admin-release", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({session_id: sessionId, admin_password})
      });
      showStatus("工位已释放");
      await loadStationSessions();
    }

    refreshAll().catch(err => showStatus(err.message));
    refreshClientReleases().catch(() => {});
    refreshClientUpdateLogs().catch(() => {});
  </script>
</body>
</html>
"""
