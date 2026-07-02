HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>关键工位防错追溯系统 - 管理后台</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: Arial, "Microsoft YaHei", sans-serif; color: #111827; background: #f3f4f6; }
    header { height: 64px; display: flex; align-items: center; justify-content: space-between; padding: 0 24px; background: #111827; color: white; }
    header h1 { font-size: 22px; margin: 0; font-weight: 700; }
    .account-summary { display: flex; align-items: center; gap: 14px; font-size: 14px; }
    .account-summary a { color: white; }
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
    .tree-route { margin-left: 14px; color: #1d4ed8; font-weight: 700; cursor: default; }
    .tree-route:hover { background: transparent; }
    .tree-station { margin-left: 28px; }
    .tree-step { margin-left: 42px; color: #4b5563; }
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
    select[multiple] { height: 110px; min-width: 240px; }
    .checkbox-label { display: inline-flex; align-items: center; gap: 8px; height: 38px; }
    button.primary { height: 38px; padding: 0 18px; border: 0; border-radius: 6px; background: #2563eb; color: white; font-size: 15px; font-weight: 700; cursor: pointer; }
    button.secondary { height: 38px; padding: 0 18px; border: 1px solid #cbd5e1; border-radius: 6px; background: white; font-size: 15px; cursor: pointer; }
    button.danger { height: 38px; padding: 0 18px; border: 0; border-radius: 6px; background: #dc2626; color: white; font-size: 15px; cursor: pointer; }
    table { width: 100%; border-collapse: collapse; background: white; }
    th, td { border: 1px solid #e5e7eb; padding: 10px; text-align: left; font-size: 14px; }
    th { background: #f9fafb; }
    .hint { color: #6b7280; font-size: 14px; }
    .status { min-height: 24px; color: #2563eb; font-weight: 700; }
    .route-layout { display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 16px; }
    .route-tree { border: 1px solid #d1d5db; border-radius: 6px; min-height: 420px; padding: 10px; background: #f9fafb; }
    .route-group { margin-bottom: 14px; }
    .route-group-title { padding: 8px; font-weight: 700; color: #1d4ed8; border-bottom: 1px solid #dbeafe; }
    .route-station { width: 100%; padding: 9px 10px; margin-top: 4px; text-align: left; border: 0; border-radius: 5px; background: transparent; cursor: pointer; }
    .route-station:hover { background: #dbeafe; }
    .route-station.active { background: #2563eb; color: white; }
    .route-note { padding: 12px; border-left: 4px solid #2563eb; background: #eff6ff; line-height: 1.7; }
    @media (max-width: 1000px) { .route-layout { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header>
    <h1>关键工位防错追溯系统 - 管理后台</h1>
    <div class="account-summary">
      <span>当前用户：<strong id="currentUsername">-</strong></span>
      <span>角色：<strong id="currentRole">-</strong></span>
      <a href="/logout">退出登录</a>
    </div>
  </header>
  <div class="layout">
    <nav>
      <button class="tab active" data-page="projectPage">项目管理</button>
      <button class="tab" data-page="stationPage">工位管理</button>
      <button class="tab" data-page="stepPage">工序规则管理</button>
      <button class="tab" data-page="routePage">工艺路线配置</button>
      <button class="tab" data-page="recordPage">扫描记录查询</button>
      <button class="tab" data-page="maintenancePage">系统维护</button>
      <button class="tab" data-page="accountPage">账号与安全</button>
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
            <label>物料编码</label>
            <input id="projectMaterialCode" placeholder="例如：A / B">
            <label>产品类型</label>
            <input id="projectProductType" placeholder="例如：A物料">
            <button class="primary" onclick="addProject()">添加项目</button>
            <button class="primary" onclick="updateProject()">保存修改</button>
            <button class="secondary" onclick="resetProjectForm()">取消编辑</button>
          </div>
          <p class="hint">最大层级：项目。支持新增、修改、删除；删除项目会清理下属工位、工序和记录。</p>
        </div>
        <div class="panel">
          <h2>项目列表 <span class="hint" id="selectedProjectText"></span></h2>
          <table>
            <thead><tr><th>ID</th><th>项目名称</th><th>物料编码</th><th>产品类型</th><th>工位数量</th><th>创建时间</th><th>操作</th></tr></thead>
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
            <label>所属路线</label>
            <select id="stationRoute">
              <option>A主线</option><option>B子线</option>
              <option>返修线</option><option>其他</option>
            </select>
            <label>路线顺序</label>
            <input id="stationRouteOrder" type="number" min="0" value="0">
            <label>工位作用</label>
            <select id="stationRole">
              <option>普通工位</option><option>起点工位</option>
              <option>PLC起点</option><option>主条码切换工位</option>
              <option>合并绑定工位</option><option>后续工位</option>
              <option>B起点工位</option><option>B完成工位</option>
            </select>
            <button class="primary" onclick="addStation()">添加工位</button>
            <button class="primary" onclick="updateStation()">保存修改</button>
            <button class="secondary" onclick="resetStationForm()">取消编辑</button>
          </div>
          <p class="hint">中间层级：工位。桌面端在线模式会按项目和工位下载对应工序。</p>
        </div>
        <div class="panel">
          <h2>工位列表 <span class="hint" id="selectedStationProjectText"></span></h2>
          <table>
            <thead><tr><th>项目</th><th>路线</th><th>顺序</th><th>工位</th><th>工位作用</th><th>创建时间</th><th>操作</th></tr></thead>
            <tbody id="stationRows"></tbody>
          </table>
        </div>
        <div class="panel">
          <h2>工位进入前置条件</h2>
          <div class="toolbar">
            <label class="checkbox-label"><input id="depPrevious" type="checkbox" checked> 必须完成上一工位</label>
            <label class="checkbox-label"><input id="depSwitch" type="checkbox"> 必须完成主条码切换</label>
            <label class="checkbox-label"><input id="depCurrentBarcode" type="checkbox"> 必须使用当前有效主条码</label>
            <label>必须完成的指定工位</label>
            <select id="depStationIds" multiple></select>
          </div>
          <div class="toolbar">
            <label>子物料项目</label>
            <select id="depChildProject" onchange="refreshDependencyStationOptions()"><option value="">不限制</option></select>
            <label>子物料类型</label>
            <input id="depChildType" placeholder="例如：B">
            <label>数量</label>
            <input id="depChildCount" type="number" min="0" value="0">
            <label>子物料必完工位</label>
            <select id="depChildStationIds" multiple></select>
            <button class="primary" onclick="saveStationDependency()">保存前置条件</button>
            <button class="secondary" onclick="loadStationDependency()">重新加载</button>
          </div>
          <p class="hint">后续工位统一按这里校验上一工位、指定工位、主条码切换和跨产线子物料完成状态。</p>
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
              <option value="plc_magnet_check">PLC磁通检测获取</option>
              <option value="主条码切换">主条码切换</option>
              <option value="子物料绑定">子物料绑定</option>
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
          <div id="plcMagnetFields" style="display:none">
            <div class="toolbar">
              <label class="checkbox-label"><input id="magnetPlcEnabled" type="checkbox" checked> 启用PLC</label>
              <label>PLC IP</label><input id="magnetPlcIp" value="192.168.111.50">
              <label>Rack</label><input id="magnetPlcRack" type="number" value="0">
              <label>Slot</label><input id="magnetPlcSlot" type="number" value="1">
              <label>DB</label><input id="magnetPlcDb" type="number" value="221">
            </div>
            <div class="toolbar">
              <label>轮询ms</label><input id="magnetPollMs" type="number" value="300">
              <label>超时秒</label><input id="magnetTimeoutSeconds" type="number" value="30">
              <label>块起始</label><input id="magnetBlockStart" type="number" value="0">
              <label>块长度</label><input id="magnetBlockSize" type="number" min="26" value="26">
              <label>OK值</label><input id="magnetOkValue" type="number" value="1">
            </div>
            <div class="toolbar">
              <label>DBW0准备</label><input id="magnetBarcodeOkOffset" type="number" value="0">
              <label>DBW2夹紧</label><input id="magnetCylinderOffset" type="number" value="2">
              <label>DBW4拧紧</label><input id="magnetScrewOffset" type="number" value="4">
              <label>DBW6检测完成</label><input id="magnetCompleteOffset" type="number" value="6">
              <label>DBW8结束</label><input id="magnetReadDoneOffset" type="number" value="8">
            </div>
            <div class="toolbar">
              <label>DBD10左磁通</label><input id="magnetLeftFluxOffset" type="number" value="10">
              <label>DBW14左极性</label><input id="magnetLeftPolarityOffset" type="number" value="14">
              <label>DBW16左判定</label><input id="magnetLeftResultOffset" type="number" value="16">
              <label>DBD18右磁通</label><input id="magnetRightFluxOffset" type="number" value="18">
              <label>DBW22右极性</label><input id="magnetRightPolarityOffset" type="number" value="22">
              <label>DBW24右判定</label><input id="magnetRightResultOffset" type="number" value="24">
            </div>
            <div class="toolbar">
              <label>写入读回次数</label><input id="magnetVerifyRetries" type="number" min="1" value="3">
              <label>读回间隔ms</label><input id="magnetVerifyInterval" type="number" value="100">
            </div>
            <p class="hint">DBW0、DBW4写1后读回确认；DBW8只写1不回读，由PLC立即复位。原始块最少读取26字节。</p>
          </div>
          <div id="switchFields" style="display:none">
            <div class="toolbar">
              <label class="checkbox-label"><input id="switchRequireOld" type="checkbox" checked> 必须扫描旧码</label>
              <label class="checkbox-label"><input id="switchRequireNew" type="checkbox" checked> 必须扫描新码</label>
              <label class="checkbox-label"><input id="switchSetCurrent" type="checkbox" checked> 新码设为当前主条码</label>
              <label class="checkbox-label"><input id="switchDisableOld" type="checkbox" checked> 禁止旧码继续生产</label>
            </div>
          </div>
          <div id="bindFields" style="display:none">
            <div class="toolbar">
              <label>绑定模式</label>
              <select id="bindMode" onchange="toggleBindMode()">
                <option value="material_type">按子物料类型绑定</option>
                <option value="completed_step_barcode">按完成工序绑定主条码</option>
              </select>
              <label>父件物料类型</label><select id="bindParentType" disabled></select>
              <label>子物料项目</label><select id="bindChildProject" onchange="refreshBindingOptions()"><option value="">同当前项目</option></select>
              <label>子件物料类型</label><select id="bindChildType"></select>
              <label>子件路线</label><select id="bindChildRoute" onchange="refreshBindingOptions()"></select>
              <label>子物料数量</label><input id="bindRequiredCount" type="number" min="1" value="1">
              <label>子物料必完工位</label><select id="bindRequiredStationIds" multiple></select>
            </div>
            <p class="hint">A/B并行路线优先按子件路线和必完工位校验；绑定时扫描B线路当前主条码。物料类型仅用于分类和旧配置兼容。</p>
            <div class="toolbar">
              <label class="checkbox-label"><input id="bindRequireSwitch" type="checkbox" checked> 父件必须已切换主条码</label>
              <label class="checkbox-label"><input id="bindAllowDuplicate" type="checkbox"> 允许重复绑定</label>
              <label class="checkbox-label"><input id="bindAllowUnbind" type="checkbox"> 允许管理员解绑</label>
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

      <section id="routePage" class="page">
        <div class="panel">
          <h2>工艺路线配置</h2>
          <div class="toolbar">
            <label>项目</label>
            <select id="routeProject" onchange="onRouteProjectChanged()"></select>
            <label>从模板创建路线</label>
            <select id="routeTemplate">
              <option>普通串行路线</option>
              <option>PLC首工位路线</option>
              <option>主条码切换路线</option>
              <option>B子线两工位路线</option>
              <option selected>A主线绑定B子线路线</option>
            </select>
            <button class="primary" onclick="applyRouteTemplate()">创建路线</button>
          </div>
          <div class="route-note">
            A主线和B子线可以并行生产。B子线顺序由自己的工位依赖控制；
            A和B只在A合并B工位通过“子物料绑定”建立关系。
            普通扫码工序不会自动绑定B。
          </div>
        </div>
        <div class="route-layout">
          <div class="panel">
            <h2>1. 路线/工位编排</h2>
            <div id="routeTree" class="route-tree"></div>
          </div>
          <div>
            <div class="panel">
              <h2>工位信息 <span id="routeStationIdText" class="hint"></span></h2>
              <div class="toolbar">
                <label>工位名称</label><input id="routeStationName">
                <label>所属路线</label>
                <select id="routeName">
                  <option>A主线</option><option>B子线</option>
                  <option>返修线</option><option>其他</option>
                </select>
                <label>路线内顺序</label><input id="routeOrder" type="number" min="0">
              </div>
              <div class="toolbar">
                <label>工位作用</label>
                <select id="routeStationRole">
                  <option>普通工位</option><option>起点工位</option>
                  <option>PLC起点</option><option>主条码切换工位</option>
                  <option>合并绑定工位</option><option>后续工位</option>
                  <option>B起点工位</option><option>B完成工位</option>
                </select>
                <label>物料类型</label>
                <select id="routeMaterialType">
                  <option>A物料</option><option>B物料</option>
                </select>
                <button class="primary" onclick="saveRouteStation()">保存工位编排</button>
              </div>
              <p class="hint">路线顺序仅用于显示；生产放行只读取下面保存的显式依赖。</p>
            </div>
            <div class="panel">
              <h2>2. 工位规则配置</h2>
              <button class="secondary" onclick="openSelectedStationRules()">在规则管理中配置</button>
              <table>
                <thead><tr><th>顺序</th><th>名称</th><th>功能</th><th>主条码</th><th>操作</th></tr></thead>
                <tbody id="routeRuleRows"></tbody>
              </table>
            </div>
            <div class="panel">
              <h2>3. 绑定/合并配置</h2>
              <div id="routeBindingSummary" class="hint">当前工位未配置子物料绑定。</div>
            </div>
            <div class="panel">
              <h2>4. 工位依赖配置</h2>
              <div class="toolbar">
                <label class="checkbox-label"><input id="routeDepPrevious" type="checkbox"> 兼容旧逻辑：上一工位</label>
                <label class="checkbox-label"><input id="routeDepSwitch" type="checkbox"> 必须完成主条码切换</label>
                <label class="checkbox-label"><input id="routeDepCurrent" type="checkbox"> 必须使用当前有效主条码</label>
              </div>
              <div class="toolbar">
                <label>必须完成工位</label><select id="routeDepStationIds" multiple></select>
                <label>必须绑定子物料数量</label><input id="routeDepChildCount" type="number" min="0" value="0">
                <label>子物料类型</label><input id="routeDepChildType" placeholder="B物料">
                <label>子物料必完工位</label><select id="routeDepChildStationIds" multiple></select>
                <button class="primary" onclick="saveRouteDependency()">保存依赖</button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="recordPage" class="page">
        <div class="panel">
          <h2>产品实体追溯</h2>
          <div class="toolbar">
            <label>任意条码</label>
            <input id="traceBarcode" placeholder="旧A码 / 新A码 / B码">
            <button class="primary" onclick="loadProductTrace()">查询完整追溯</button>
          </div>
          <pre id="traceResult" style="white-space:pre-wrap;background:#f9fafb;border:1px solid #e5e7eb;padding:12px;border-radius:6px;"></pre>
        </div>
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
            <label>渠道</label>
            <select id="releaseChannel">
              <option value="stable">stable 正式版</option>
              <option value="debug">debug 调试版</option>
            </select>
            <label class="checkbox-label"><input id="releaseActive" type="checkbox" checked> 启用此版本</label>
          </div>
          <div class="toolbar">
            <input id="releaseNotes" placeholder="更新说明，多条用 | 分隔" style="min-width:320px; flex:1">
          </div>
          <div class="toolbar">
            <label>客户端程序</label><input id="updateFile" type="file" accept=".exe,.zip,application/zip,application/octet-stream">
            <button id="saveClientReleaseBtn" class="primary" onclick="saveClientRelease()">上传更新包</button>
            <button class="secondary" onclick="refreshClientReleases()">刷新版本</button>
          </div>
          <div class="hint">支持 EXE 或 ZIP。stable ZIP必须包含 QualityControlSystem.exe；debug ZIP必须包含 QualityControlSystem_Debug.exe。单个文件最大500MB。</div>
          <table>
            <thead><tr><th>版本</th><th>标题</th><th>发布时间</th><th>稳定</th><th>强制</th><th>说明</th><th>上传文件</th><th>操作</th></tr></thead>
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

      <section id="accountPage" class="page">
        <div class="panel">
          <h2>修改自己的密码</h2>
          <div id="changePasswordArea">
            <div class="toolbar">
              <label>旧密码</label><input id="oldPassword" type="password" autocomplete="current-password">
              <label>新密码</label><input id="newPassword" type="password" autocomplete="new-password">
              <label>确认新密码</label><input id="confirmPassword" type="password" autocomplete="new-password">
              <button class="primary" onclick="changeOwnPassword()">修改密码</button>
            </div>
            <p class="hint">新密码至少8位，不能使用常见弱密码；修改成功后需要重新登录。</p>
          </div>
          <p id="superPasswordHint" class="hint" style="display:none">超级管理员密码只能通过服务器维护脚本重置。</p>
        </div>
        <div class="panel">
          <h2>后台用户管理</h2>
          <div class="toolbar">
            <label>用户名</label><input id="newAdminUsername">
            <label>显示名称</label><input id="newAdminDisplayName">
            <label>初始密码</label><input id="newAdminPassword" type="password">
            <button class="primary" onclick="createAdminUser()">新增管理员</button>
            <button class="secondary" onclick="loadAdminUsers()">刷新</button>
          </div>
          <table>
            <thead><tr><th>用户名</th><th>显示名称</th><th>角色</th><th>启用</th><th>内置</th><th>最后登录</th><th>操作</th></tr></thead>
            <tbody id="adminUserRows"></tbody>
          </table>
        </div>
        <div class="panel">
          <h2>登录安全日志</h2>
          <button class="secondary" onclick="loadLoginLogs()">刷新日志</button>
          <table>
            <thead><tr><th>时间</th><th>账号</th><th>角色</th><th>IP</th><th>结果</th><th>消息</th></tr></thead>
            <tbody id="loginLogRows"></tbody>
          </table>
        </div>
      </section>
    </main>
  </div>

  <script>
    let fullData = {projects: []};
    let selectedProjectId = null;
    let selectedStationId = null;
    let currentUser = null;
    const expandedProjects = new Set();
    const expandedStations = new Set();

    function showStatus(text, timeout = 3000) {
      document.getElementById("status").textContent = text || "";
      if (text && timeout > 0) setTimeout(() => showStatus(""), timeout);
    }

    async function api(path, options = {}) {
      const res = await fetch(path, options);
      const data = await res.json().catch(() => ({}));
      if (res.status === 401) {
        window.location.href = "/login";
        throw new Error("登录已过期");
      }
      if (!res.ok) throw new Error(data.error || data.msg || data.message || "请求失败");
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

    function stepTypeLabel(value) {
      if (value === "plc_magnet_check" || value === "PLC磁通检测获取") {
        return "PLC磁通检测获取";
      }
      return value || "";
    }

    document.querySelectorAll(".tab").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach(item => item.classList.remove("active"));
        document.querySelectorAll(".page").forEach(item => item.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById(btn.dataset.page).classList.add("active");
        if (btn.dataset.page === "routePage") renderRoutePage();
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
      await loadStationDependency();
      renderRoutePage();
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

    function onRouteProjectChanged() {
      selectedProjectId = Number(document.getElementById("routeProject").value);
      const project = currentProject();
      selectedStationId = project && project.stations.length ? project.stations[0].id : null;
      renderMenuTree();
      renderRoutePage();
    }

    function selectRouteStation(projectId, stationId) {
      selectedProjectId = Number(projectId);
      selectedStationId = Number(stationId);
      expandedProjects.add(selectedProjectId);
      expandedStations.add(selectedStationId);
      refreshProjectOptions();
      refreshStationOptions();
      renderMenuTree();
      renderRoutePage();
    }

    function renderRoutePage() {
      const projectSelect = document.getElementById("routeProject");
      if (!projectSelect) return;
      if (selectedProjectId) projectSelect.value = selectedProjectId;
      const project = currentProject();
      const station = currentStation();
      const groups = {};
      (project ? project.stations : []).forEach(item => {
        const route = item.route_name || "A主线";
        (groups[route] ||= []).push(item);
      });
      document.getElementById("routeTree").innerHTML = Object.entries(groups)
        .sort(([left], [right]) => routeSortValue(left) - routeSortValue(right) || left.localeCompare(right, "zh-CN"))
        .map(([route, stations]) => {
          const rows = stations
            .sort((left, right) => (left.route_order || 0) - (right.route_order || 0) || left.id - right.id)
            .map(item => `<button class="route-station ${item.id === selectedStationId ? "active" : ""}" data-station-id="${item.id}" onclick="selectRouteStation(${project.id}, ${item.id})">${item.route_order || 0}. ${htmlEscape(item.name)}<br><small>${htmlEscape(item.station_role || "普通工位")} / ${htmlEscape(item.material_type || "未设置物料")}</small></button>`)
            .join("");
          return `<div class="route-group"><div class="route-group-title">${htmlEscape(route)}</div>${rows}</div>`;
        }).join("") || `<div class="hint">当前项目暂无路线工位，可从模板创建。</div>`;

      document.getElementById("routeStationIdText").textContent = station ? `station_id=${station.id}` : "";
      document.getElementById("routeStationName").value = station ? station.name : "";
      document.getElementById("routeName").value = station ? (station.route_name || "A主线") : "A主线";
      document.getElementById("routeOrder").value = station ? (station.route_order || 0) : 0;
      document.getElementById("routeStationRole").value = station ? (station.station_role || "普通工位") : "普通工位";
      setMaterialTypeOptions(
        "routeMaterialType",
        project ? project.id : null,
        station ? station.material_type : ""
      );

      const steps = station ? (station.steps || []) : [];
      document.getElementById("routeRuleRows").innerHTML = steps.map(step =>
        `<tr><td>${step.step_order}</td><td>${htmlEscape(step.name)}</td><td>${htmlEscape(stepTypeLabel(step.type))}</td><td>${step.is_main_barcode ? "是" : "否"}</td><td><button class="secondary" onclick="selectStep(${project.id}, ${station.id}, ${step.id})">编辑</button></td></tr>`
      ).join("") || `<tr><td colspan="5">当前工位暂无规则</td></tr>`;

      const bindings = steps.filter(step => step.type === "子物料绑定");
      document.getElementById("routeBindingSummary").innerHTML = bindings.map(step => {
        const stationNames = (step.bind_required_station_ids || []).map(id => {
          for (const candidateProject of fullData.projects) {
            const found = candidateProject.stations.find(item => item.id === Number(id));
            if (found) return found.name;
          }
          return `station_id=${id}`;
        });
        return `<div><strong>${htmlEscape(step.name)}</strong><br>
          父件路线：${htmlEscape(station.route_name || "A主线")}；父件物料：${htmlEscape(station.material_type || "")}；父件条码：当前有效主条码<br>
          绑定模式：${step.bind_mode === "completed_step_barcode" ? "按完成工序绑定主条码" : "按子物料类型绑定"}；
          子件路线：${htmlEscape(step.bind_child_route || "未设置")}；子件物料：${htmlEscape(step.bind_child_material_type || "")}；数量：${step.bind_required_count || 1}<br>
          子件必须完成：${htmlEscape(stationNames.join("、") || "未设置")}；
          ${step.bind_require_parent_switch ? "父件必须完成主条码切换；" : ""}
          B只能绑定一次且不能绑定多个A
          <button class="secondary" onclick="selectStep(${project.id}, ${station.id}, ${step.id})">编辑绑定规则</button>
        </div>`;
      }).join("") || "当前工位未配置子物料绑定。只有“子物料绑定”工序会建立A-B关系。";

      const dependency = station ? (station.dependency || {}) : {};
      const stationOptionsHtml = (project ? project.stations : [])
        .filter(item => !station || item.id !== station.id)
        .map(item => `<option value="${item.id}">${htmlEscape(item.route_name || "A主线")} / ${htmlEscape(item.name)}</option>`)
        .join("");
      document.getElementById("routeDepStationIds").innerHTML = stationOptionsHtml;
      document.getElementById("routeDepChildStationIds").innerHTML = (project ? project.stations : [])
        .filter(item => item.material_type === "B物料" || item.route_name === "B子线")
        .map(item => `<option value="${item.id}">${htmlEscape(item.name)}</option>`)
        .join("");
      document.getElementById("routeDepPrevious").checked = !!dependency.require_previous_station;
      document.getElementById("routeDepSwitch").checked = !!dependency.require_barcode_switch;
      document.getElementById("routeDepCurrent").checked = !!dependency.require_current_barcode;
      document.getElementById("routeDepChildCount").value = dependency.required_child_count || 0;
      document.getElementById("routeDepChildType").value = dependency.required_child_material_type || "";
      setSelectedIds("routeDepStationIds", dependency.required_station_ids || []);
      setSelectedIds("routeDepChildStationIds", dependency.required_child_station_ids || []);
    }

    async function saveRouteStation() {
      const project = currentProject();
      const station = currentStation();
      if (!project || !station) return showStatus("请先选择工位");
      await api(`/api/stations/${station.id}`, {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          project_id: project.id,
          name: document.getElementById("routeStationName").value.trim(),
          route_name: document.getElementById("routeName").value,
          route_order: Number(document.getElementById("routeOrder").value || 0),
          station_role: document.getElementById("routeStationRole").value,
          material_type: document.getElementById("routeMaterialType").value
        })
      });
      showStatus("工位编排已保存");
      await refreshAll();
    }

    async function saveRouteDependency() {
      const project = currentProject();
      const station = currentStation();
      if (!project || !station) return showStatus("请先选择工位");
      await api(`/api/stations/${station.id}/dependencies`, {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          require_previous_station: document.getElementById("routeDepPrevious").checked,
          require_barcode_switch: document.getElementById("routeDepSwitch").checked,
          require_current_barcode: document.getElementById("routeDepCurrent").checked,
          required_station_ids: selectedIds("routeDepStationIds"),
          required_child_project_id: Number(document.getElementById("routeDepChildCount").value || 0) > 0 ? project.id : null,
          required_child_material_type: document.getElementById("routeDepChildType").value.trim(),
          required_child_count: Number(document.getElementById("routeDepChildCount").value || 0),
          required_child_station_ids: selectedIds("routeDepChildStationIds")
        })
      });
      showStatus("显式工位依赖已保存");
      await refreshAll();
    }

    async function applyRouteTemplate() {
      const projectId = Number(document.getElementById("routeProject").value || selectedProjectId);
      const template = document.getElementById("routeTemplate").value;
      if (!projectId) return showStatus("请先选择项目");
      if (!confirm(`确定在当前项目新增“${template}”吗？模板不会修改已有工位。`)) return;
      try {
        await api(`/api/projects/${projectId}/route-template`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({template})
        });
      } catch (err) {
        return showStatus(err.message);
      }
      selectedProjectId = projectId;
      selectedStationId = null;
      showStatus("路线模板已创建");
      await refreshAll();
      setActivePage("routePage");
    }

    function openSelectedStationRules() {
      const station = currentStation();
      if (!station) return showStatus("请先选择工位");
      refreshProjectOptions();
      refreshStationOptions();
      document.getElementById("stepProject").value = selectedProjectId;
      document.getElementById("stepStation").value = selectedStationId;
      loadSteps();
      setActivePage("stepPage");
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
      loadStationDependency();
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
        const routeGroups = {};
        project.stations.forEach(station => {
          const route = station.route_name || "A主线";
          (routeGroups[route] ||= []).push(station);
        });
        const stationHtml = Object.entries(routeGroups)
          .sort(([left], [right]) => routeSortValue(left) - routeSortValue(right) || left.localeCompare(right, "zh-CN"))
          .map(([route, stations]) => {
            const rows = stations
              .sort((left, right) => Number(left.route_order || 0) - Number(right.route_order || 0) || left.id - right.id)
              .map(station => {
                const stationActive = station.id === selectedStationId;
                const stationExpanded = expandedStations.has(station.id);
                const stationSign = stationExpanded ? "-" : "+";
                const steps = station.steps || [];
                const stepHtml = steps.map(step =>
                  `<div class="tree-node tree-step" onclick="selectStep(${project.id}, ${station.id}, ${step.id})"><span class="tree-spacer"></span><span class="tree-label">规则：${htmlEscape(step.name)}</span></div>`
                ).join("");
                return `<div class="tree-node tree-station ${stationActive ? "active" : ""}" onclick="selectStation(${project.id}, ${station.id})"><span class="tree-toggle" onclick="toggleStation(event, ${project.id}, ${station.id})">${stationSign}</span><span class="tree-label">${station.route_order || 0}. ${htmlEscape(station.name)}</span></div>${stationExpanded ? stepHtml : ""}`;
              }).join("");
            return `<div class="tree-node tree-route"><span class="tree-spacer"></span><span class="tree-label">${htmlEscape(route)}</span></div>${rows}`;
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
        `<tr><td>${project.id}</td><td>${htmlEscape(project.name)}</td><td>${htmlEscape(project.material_code || "")}</td><td>${htmlEscape(project.product_type || "")}</td><td>${project.stations.length}</td><td>${project.created_at}</td><td><button class="secondary" onclick="selectProject(${project.id})">选择</button> <button class="secondary" onclick="editProject(${project.id})">编辑</button> <button class="danger" onclick="deleteProject(${project.id})">删除</button></td></tr>`
      ).join("");
      document.getElementById("projectRows").innerHTML = rows || `<tr><td colspan="7">暂无项目</td></tr>`;
    }

    function renderStations() {
      const project = currentProject();
      const stations = project ? [...project.stations].sort(
        (left, right) => routeSortValue(left.route_name) - routeSortValue(right.route_name)
          || String(left.route_name || "").localeCompare(String(right.route_name || ""), "zh-CN")
          || Number(left.route_order || 0) - Number(right.route_order || 0)
          || left.id - right.id
      ) : [];
      const rows = stations.map(station =>
        `<tr><td>${htmlEscape(project.name)}</td><td>${htmlEscape(station.route_name || "A主线")}</td><td>${station.route_order || 0}</td><td>${htmlEscape(station.name)}</td><td>${htmlEscape(station.station_role || "普通工位")}</td><td>${station.created_at}</td><td><button class="secondary" onclick="selectStation(${project.id}, ${station.id})">选择</button> <button class="secondary" onclick="editStation(${station.id})">编辑</button> <button class="danger" onclick="deleteStation(${station.id})">删除</button></td></tr>`
      ).join("");
      document.getElementById("stationRows").innerHTML = rows || `<tr><td colspan="7">暂无工位</td></tr>`;
    }

    function routeSortValue(routeName) {
      return {"A主线": 1, "B子线": 2, "返修线": 3, "其他": 4}[routeName || "A主线"] || 99;
    }

    function refreshProjectOptions() {
      ["stationProject", "stepProject", "routeProject"].forEach(id => {
        const select = document.getElementById(id);
        select.innerHTML = fullData.projects.map(project => `<option value="${project.id}">${htmlEscape(project.name)}</option>`).join("");
        if (selectedProjectId) select.value = selectedProjectId;
      });
      ["depChildProject", "bindChildProject"].forEach(id => {
        const select = document.getElementById(id);
        const current = select.value;
        const emptyLabel = id === "bindChildProject" ? "同当前项目" : "不限制";
        select.innerHTML = `<option value="">${emptyLabel}</option>` + fullData.projects.map(
          project => `<option value="${project.id}">${htmlEscape(project.name)}</option>`
        ).join("");
        if (current) select.value = current;
      });
      refreshDependencyStationOptions();
      refreshBindingOptions();
    }

    function refreshStationOptions() {
      const projectId = Number(document.getElementById("stepProject").value || selectedProjectId);
      const project = fullData.projects.find(item => item.id === projectId) || fullData.projects[0];
      const select = document.getElementById("stepStation");
      select.innerHTML = project ? project.stations.map(station => `<option value="${station.id}">${htmlEscape(station.name)}</option>`).join("") : "";
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
      refreshBindingOptions();
      loadSteps();
    }

    async function addProject() {
      const name = document.getElementById("projectName").value.trim();
      if (!name) return showStatus("项目名称不能为空");
      const material_code = document.getElementById("projectMaterialCode").value.trim();
      const product_type = document.getElementById("projectProductType").value.trim();
      await api("/api/projects", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name, material_code, product_type})
      });
      document.getElementById("projectName").value = "";
      document.getElementById("projectMaterialCode").value = "";
      document.getElementById("projectProductType").value = "";
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
      document.getElementById("projectMaterialCode").value = project.material_code || "";
      document.getElementById("projectProductType").value = project.product_type || "";
      renderMenuTree();
      renderStations();
      refreshProjectOptions();
      refreshStationOptions();
      showStatus("正在编辑项目");
    }

    function resetProjectForm() {
      document.getElementById("projectId").value = "";
      document.getElementById("projectName").value = "";
      document.getElementById("projectMaterialCode").value = "";
      document.getElementById("projectProductType").value = "";
    }

    async function updateProject() {
      const id = document.getElementById("projectId").value;
      const name = document.getElementById("projectName").value.trim();
      const material_code = document.getElementById("projectMaterialCode").value.trim();
      const product_type = document.getElementById("projectProductType").value.trim();
      if (!id) return showStatus("请先在项目列表点击编辑");
      if (!name) return showStatus("项目名称不能为空");
      await api(`/api/projects/${id}`, {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name, material_code, product_type})
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
        body: JSON.stringify({
          project_id,
          name,
          route_name: document.getElementById("stationRoute").value,
          route_order: Number(document.getElementById("stationRouteOrder").value || 0),
          station_role: document.getElementById("stationRole").value
        })
      });
      resetStationForm();
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
      document.getElementById("stationRoute").value = station.route_name || "A主线";
      document.getElementById("stationRouteOrder").value = station.route_order || 0;
      document.getElementById("stationRole").value = station.station_role || "普通工位";
      renderMenuTree();
      renderStations();
      showStatus("正在编辑工位");
    }

    function resetStationForm() {
      document.getElementById("stationId").value = "";
      document.getElementById("stationName").value = "";
      document.getElementById("stationRoute").value = "A主线";
      document.getElementById("stationRouteOrder").value = 0;
      document.getElementById("stationRole").value = "普通工位";
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
        body: JSON.stringify({
          project_id,
          name,
          route_name: document.getElementById("stationRoute").value,
          route_order: Number(document.getElementById("stationRouteOrder").value || 0),
          station_role: document.getElementById("stationRole").value
        })
      });
      resetStationForm();
      showStatus("工位已修改");
      refreshAll();
    }

    function toggleStepFields() {
      const type = document.getElementById("stepType").value;
      const isScrew = type === "螺丝";
      const isPlc = type === "PLC接收";
      const isMagnet = type === "plc_magnet_check";
      const isScan = type === "扫码";
      const isSwitch = type === "主条码切换";
      const isBind = type === "子物料绑定";
      document.getElementById("barcodeFields").style.display = isScan ? "flex" : "none";
      document.getElementById("screwFields").style.display = isScrew ? "flex" : "none";
      document.getElementById("plcFields").style.display = isPlc ? "block" : "none";
      document.getElementById("plcMagnetFields").style.display = isMagnet ? "block" : "none";
      document.getElementById("switchFields").style.display = isSwitch ? "block" : "none";
      document.getElementById("bindFields").style.display = isBind ? "block" : "none";
      if (isBind) toggleBindMode();
      const mainBarcode = document.getElementById("isMainBarcode");
      mainBarcode.disabled = !isScan;
      if (!isScan) mainBarcode.checked = false;
    }

    function toggleBindMode() {
      const completedStepMode = document.getElementById("bindMode").value === "completed_step_barcode";
      document.getElementById("bindChildType").disabled = completedStepMode;
      document.getElementById("bindChildRoute").disabled = !completedStepMode;
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
        plc_barcode_wait_ok_timeout_seconds: Number(document.getElementById("plcBarcodeWaitOkTimeoutSeconds").value || 30),
        plc_magnet_config: {
          plc_enabled: document.getElementById("magnetPlcEnabled").checked,
          plc_ip: document.getElementById("magnetPlcIp").value.trim(),
          plc_rack: Number(document.getElementById("magnetPlcRack").value || 0),
          plc_slot: Number(document.getElementById("magnetPlcSlot").value || 1),
          plc_db: Number(document.getElementById("magnetPlcDb").value || 221),
          plc_poll_interval_ms: Number(document.getElementById("magnetPollMs").value || 300),
          plc_timeout_seconds: Number(document.getElementById("magnetTimeoutSeconds").value || 30),
          barcode_ok_offset: Number(document.getElementById("magnetBarcodeOkOffset").value || 0),
          cylinder_clamped_offset: Number(document.getElementById("magnetCylinderOffset").value || 2),
          screw_complete_offset: Number(document.getElementById("magnetScrewOffset").value || 4),
          magnet_complete_offset: Number(document.getElementById("magnetCompleteOffset").value || 6),
          mes_read_done_offset: Number(document.getElementById("magnetReadDoneOffset").value || 8),
          left_flux_offset: Number(document.getElementById("magnetLeftFluxOffset").value || 10),
          left_polarity_offset: Number(document.getElementById("magnetLeftPolarityOffset").value || 14),
          left_result_offset: Number(document.getElementById("magnetLeftResultOffset").value || 16),
          right_flux_offset: Number(document.getElementById("magnetRightFluxOffset").value || 18),
          right_polarity_offset: Number(document.getElementById("magnetRightPolarityOffset").value || 22),
          right_result_offset: Number(document.getElementById("magnetRightResultOffset").value || 24),
          ok_value: Number(document.getElementById("magnetOkValue").value || 1),
          read_block_start: Number(document.getElementById("magnetBlockStart").value || 0),
          read_block_size: Number(document.getElementById("magnetBlockSize").value || 26),
          write_verify_retry_count: Number(document.getElementById("magnetVerifyRetries").value || 3),
          write_verify_interval_ms: Number(document.getElementById("magnetVerifyInterval").value || 100)
        },
        switch_require_old: document.getElementById("switchRequireOld").checked,
        switch_require_new: document.getElementById("switchRequireNew").checked,
        switch_set_current: document.getElementById("switchSetCurrent").checked,
        switch_disable_old: document.getElementById("switchDisableOld").checked,
        bind_child_project_id: Number(document.getElementById("bindChildProject").value || 0) || null,
        bind_mode: document.getElementById("bindMode").value || "material_type",
        bind_child_material_type: document.getElementById("bindChildType").value,
        bind_child_route: document.getElementById("bindChildRoute").value.trim(),
        bind_required_count: Number(document.getElementById("bindRequiredCount").value || 1),
        bind_required_station_ids: selectedIds("bindRequiredStationIds"),
        bind_require_parent_switch: document.getElementById("bindRequireSwitch").checked,
        bind_allow_duplicate: document.getElementById("bindAllowDuplicate").checked,
        bind_allow_unbind: document.getElementById("bindAllowUnbind").checked
      };
    }

    function fillStepForm(step) {
      document.getElementById("stepId").value = step.id || "";
      document.getElementById("stepName").value = step.name || "";
      document.getElementById("stepType").value =
        step.type === "PLC磁通检测获取" ? "plc_magnet_check" : (step.type || "扫码");
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
      const magnet = step.plc_magnet_config || {};
      document.getElementById("magnetPlcEnabled").checked = magnet.plc_enabled ?? true;
      document.getElementById("magnetPlcIp").value = magnet.plc_ip || "192.168.111.50";
      document.getElementById("magnetPlcRack").value = magnet.plc_rack ?? 0;
      document.getElementById("magnetPlcSlot").value = magnet.plc_slot ?? 1;
      document.getElementById("magnetPlcDb").value = magnet.plc_db ?? 221;
      document.getElementById("magnetPollMs").value = magnet.plc_poll_interval_ms ?? 300;
      document.getElementById("magnetTimeoutSeconds").value = magnet.plc_timeout_seconds ?? 30;
      document.getElementById("magnetBarcodeOkOffset").value = magnet.barcode_ok_offset ?? 0;
      document.getElementById("magnetCylinderOffset").value = magnet.cylinder_clamped_offset ?? 2;
      document.getElementById("magnetScrewOffset").value = magnet.screw_complete_offset ?? 4;
      document.getElementById("magnetCompleteOffset").value = magnet.magnet_complete_offset ?? 6;
      document.getElementById("magnetReadDoneOffset").value = magnet.mes_read_done_offset ?? 8;
      document.getElementById("magnetLeftFluxOffset").value = magnet.left_flux_offset ?? 10;
      document.getElementById("magnetLeftPolarityOffset").value = magnet.left_polarity_offset ?? 14;
      document.getElementById("magnetLeftResultOffset").value = magnet.left_result_offset ?? 16;
      document.getElementById("magnetRightFluxOffset").value = magnet.right_flux_offset ?? 18;
      document.getElementById("magnetRightPolarityOffset").value = magnet.right_polarity_offset ?? 22;
      document.getElementById("magnetRightResultOffset").value = magnet.right_result_offset ?? 24;
      document.getElementById("magnetOkValue").value = magnet.ok_value ?? 1;
      document.getElementById("magnetBlockStart").value = magnet.read_block_start ?? 0;
      document.getElementById("magnetBlockSize").value = magnet.read_block_size ?? 26;
      document.getElementById("magnetVerifyRetries").value = magnet.write_verify_retry_count ?? 3;
      document.getElementById("magnetVerifyInterval").value = magnet.write_verify_interval_ms ?? 100;
      document.getElementById("switchRequireOld").checked = step.switch_require_old ?? true;
      document.getElementById("switchRequireNew").checked = step.switch_require_new ?? true;
      document.getElementById("switchSetCurrent").checked = step.switch_set_current ?? true;
      document.getElementById("switchDisableOld").checked = step.switch_disable_old ?? true;
      document.getElementById("bindChildProject").value = step.bind_child_project_id || "";
      document.getElementById("bindMode").value = step.bind_mode || "material_type";
      document.getElementById("bindRequiredCount").value = step.bind_required_count ?? 1;
      refreshBindingOptions(
        step.bind_child_material_type || "",
        step.bind_child_route || ""
      );
      setSelectedIds("bindRequiredStationIds", step.bind_required_station_ids || []);
      document.getElementById("bindRequireSwitch").checked = step.bind_require_parent_switch ?? true;
      document.getElementById("bindAllowDuplicate").checked = !!step.bind_allow_duplicate;
      document.getElementById("bindAllowUnbind").checked = !!step.bind_allow_unbind;
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
        `<tr><td>${step.step_order}</td><td>${htmlEscape(step.name)}</td><td>${htmlEscape(stepTypeLabel(step.type))}</td><td>${step.required_count || ""}</td><td>${step.barcode_start}-${step.barcode_end}</td><td>${htmlEscape(step.expected_content || "")}</td><td>${step.is_main_barcode ? "是" : "否"}</td><td><button class="secondary" onclick="editStep(${step.id})">编辑</button> <button class="danger" onclick="deleteStep(${step.id})">删除</button></td></tr>`
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

    function parseIdList(value) {
      return String(value || "").split(",").map(item => Number(item.trim())).filter(Boolean);
    }

    function selectedIds(id) {
      return Array.from(document.getElementById(id).selectedOptions).map(option => Number(option.value)).filter(Boolean);
    }

    function setSelectedIds(id, ids) {
      const selected = new Set((ids || []).map(Number));
      Array.from(document.getElementById(id).options).forEach(option => {
        option.selected = selected.has(Number(option.value));
      });
    }

    function stationOptions(projectId = null, excludeStationId = null) {
      const projects = projectId
        ? fullData.projects.filter(project => project.id === Number(projectId))
        : fullData.projects;
      return projects.flatMap(project => project.stations
        .filter(station => station.id !== excludeStationId)
        .map(station => `<option value="${station.id}">${htmlEscape(project.name)} / ${htmlEscape(station.name)}</option>`)
      ).join("");
    }

    function materialTypeValues(projectId = null, selectedValue = "") {
      const values = new Set(["A物料", "B物料"]);
      const projects = projectId
        ? fullData.projects.filter(project => project.id === Number(projectId))
        : fullData.projects;
      projects.forEach(project => {
        if (project.product_type) values.add(project.product_type);
        project.stations.forEach(station => {
          if (station.material_type) values.add(station.material_type);
        });
      });
      if (selectedValue) values.add(selectedValue);
      const rank = {"A物料": 1, "B物料": 2};
      return Array.from(values).sort(
        (left, right) => (rank[left] || 99) - (rank[right] || 99)
          || left.localeCompare(right, "zh-CN")
      );
    }

    function setMaterialTypeOptions(selectId, projectId, selectedValue = "", allowEmpty = false) {
      const select = document.getElementById(selectId);
      if (!select) return;
      const values = materialTypeValues(projectId, selectedValue);
      select.innerHTML = (allowEmpty ? `<option value="">未配置</option>` : "") + values.map(
        value => `<option value="${htmlEscape(value)}">${htmlEscape(value)}</option>`
      ).join("");
      select.value = selectedValue || (allowEmpty ? "" : values[0] || "");
    }

    function refreshDependencyStationOptions() {
      const required = document.getElementById("depStationIds");
      const requiredSelected = selectedIds("depStationIds");
      required.innerHTML = stationOptions(null, selectedStationId);
      setSelectedIds("depStationIds", requiredSelected);
      const child = document.getElementById("depChildStationIds");
      const childSelected = selectedIds("depChildStationIds");
      child.innerHTML = stationOptions(document.getElementById("depChildProject").value || null);
      setSelectedIds("depChildStationIds", childSelected);
    }

    function refreshBindingOptions(selectedChildType = null, requestedRoute = null) {
      const select = document.getElementById("bindRequiredStationIds");
      const selected = selectedIds("bindRequiredStationIds");
      const configuredChildProjectId = document.getElementById("bindChildProject").value || null;
      const childProjectId = configuredChildProjectId || selectedProjectId;
      const childProject = fullData.projects.find(
        project => project.id === Number(childProjectId)
      );
      const routeSelect = document.getElementById("bindChildRoute");
      const routeValue = requestedRoute === null ? routeSelect.value : requestedRoute;
      const routes = Array.from(new Set(
        (childProject ? childProject.stations : [])
          .map(station => station.route_name || "A主线")
      ));
      routeSelect.innerHTML = `<option value="">请选择路线</option>` + routes.map(
        route => `<option value="${htmlEscape(route)}">${htmlEscape(route)}</option>`
      ).join("");
      routeSelect.value = routes.includes(routeValue) ? routeValue : "";
      select.innerHTML = (childProject ? childProject.stations : [])
        .filter(station =>
          !routeSelect.value
          || (station.route_name || "A主线") === routeSelect.value
        )
        .map(station =>
          `<option value="${station.id}">${htmlEscape(childProject.name)} / ${htmlEscape(station.name)}</option>`
        )
        .join("");
      setSelectedIds("bindRequiredStationIds", selected);
      const station = currentStation();
      setMaterialTypeOptions(
        "bindParentType",
        station ? station.project_id || selectedProjectId : selectedProjectId,
        station ? station.material_type : "",
        true
      );
      const childType = selectedChildType === null
        ? document.getElementById("bindChildType").value
        : selectedChildType;
      setMaterialTypeOptions("bindChildType", childProjectId, childType, true);
    }

    async function loadStationDependency() {
      if (!selectedStationId) return;
      const data = await api(`/api/stations/${selectedStationId}/dependencies`);
      const dep = data.dependency || {};
      refreshDependencyStationOptions();
      document.getElementById("depPrevious").checked = dep.require_previous_station ?? true;
      document.getElementById("depSwitch").checked = !!dep.require_barcode_switch;
      document.getElementById("depCurrentBarcode").checked = !!dep.require_current_barcode;
      setSelectedIds("depStationIds", dep.required_station_ids || []);
      document.getElementById("depChildProject").value = dep.required_child_project_id || "";
      refreshDependencyStationOptions();
      document.getElementById("depChildType").value = dep.required_child_material_type || "";
      document.getElementById("depChildCount").value = dep.required_child_count || 0;
      setSelectedIds("depChildStationIds", dep.required_child_station_ids || []);
    }

    async function saveStationDependency() {
      if (!selectedStationId) return showStatus("请先选择工位");
      await api(`/api/stations/${selectedStationId}/dependencies`, {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          require_previous_station: document.getElementById("depPrevious").checked,
          require_barcode_switch: document.getElementById("depSwitch").checked,
          require_current_barcode: document.getElementById("depCurrentBarcode").checked,
          required_station_ids: selectedIds("depStationIds"),
          required_child_project_id: Number(document.getElementById("depChildProject").value || 0) || null,
          required_child_material_type: document.getElementById("depChildType").value.trim(),
          required_child_count: Number(document.getElementById("depChildCount").value || 0),
          required_child_station_ids: selectedIds("depChildStationIds")
        })
      });
      showStatus("工位前置条件已保存");
      await loadStationDependency();
    }

    async function loadProductTrace() {
      const barcode = document.getElementById("traceBarcode").value.trim();
      if (!barcode) return showStatus("请输入要追溯的条码");
      const params = new URLSearchParams({barcode});
      const data = await api(`/api/product-flow/trace?${params.toString()}`);
      document.getElementById("traceResult").textContent = data.found
        ? JSON.stringify(data, null, 2)
        : "未找到该条码对应的产品实体";
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
        `<tr><td>${htmlEscape(row.version)}</td><td>${htmlEscape(row.title || "")}</td><td>${htmlEscape(row.release_date || "")}</td><td>${row.stable ? "是" : "否"}</td><td>${row.force_update ? "是" : "否"}</td><td>${htmlEscape((row.release_notes || []).join(" | "))}</td><td>${(row.update_files || []).map(file => `${htmlEscape(file.channel || "stable")} / ${file.is_active ? "启用" : "历史"}<br>${htmlEscape(file.original_name)}<br><small>${Math.ceil(Number(file.file_size || 0) / 1024)} KB / ${htmlEscape(String(file.sha256 || "").slice(0, 12))}</small><br><button class="secondary" onclick="downloadClientUpdateFile(${file.id})">下载验证</button>`).join("<br>") || "无"}</td><td><button class="secondary" onclick="downloadClientRelease('${htmlEscape(row.version)}','release')">下载正式版</button> <button class="secondary" onclick="downloadClientRelease('${htmlEscape(row.version)}','debug')">下载Debug版</button> <button class="danger" onclick="deleteClientRelease('${htmlEscape(row.version)}')">删除</button></td></tr>`
      ).join("") || `<tr><td colspan="8">暂无版本</td></tr>`;
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
      const saveButton = document.getElementById("saveClientReleaseBtn");
      const form = new FormData();
      form.append("version", version);
      form.append("remark", document.getElementById("releaseTitle").value.trim());
      form.append("release_notes", JSON.stringify(
        document.getElementById("releaseNotes").value.split("|").map(item => item.trim()).filter(Boolean)
      ));
      form.append("channel", document.getElementById("releaseChannel").value);
      form.append("is_active", document.getElementById("releaseActive").checked ? "true" : "false");
      const updateFile = readFileInput("updateFile");
      if (!updateFile) return showStatus("请选择要上传的客户端程序");
      const lowerName = updateFile.name.toLowerCase();
      if (!lowerName.endsWith(".exe") && !lowerName.endsWith(".zip")) {
        return showStatus("只支持 EXE 或 ZIP 更新包");
      }
      form.append("file", updateFile);
      saveButton.disabled = true;
      showStatus("正在上传更新包，请稍候...", 0);
      try {
        const res = await fetch("/api/client-update/upload", {method:"POST", body: form});
        const responseText = await res.text();
        let data = {};
        try { data = responseText ? JSON.parse(responseText) : {}; } catch (_) {}
        if (res.status === 401) {
          window.location.href = "/login";
          return;
        }
        if (!res.ok) {
          const detail = data.error || data.msg || data.message || responseText || "保存失败";
          throw new Error(`HTTP ${res.status}：${detail}`);
        }
        const uploaded = data.data || {};
        showStatus(`上传成功：${uploaded.file_name || updateFile.name}，${uploaded.file_size || 0} 字节`);
        document.getElementById("updateFile").value = "";
        await refreshClientReleases();
      } catch (error) {
        showStatus(`上传失败：${error.message || error}`);
      } finally {
        saveButton.disabled = false;
      }
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

    function downloadClientUpdateFile(fileId) {
      window.open(`/api/client-update/download/${fileId}`, "_blank");
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

    async function loadCurrentUser() {
      const data = await api("/api/auth/me");
      currentUser = data.user;
      document.getElementById("currentUsername").textContent = currentUser.username;
      document.getElementById("currentRole").textContent =
        currentUser.role === "super_admin" ? "超级管理员" : "管理员";
      const isSuper = currentUser.role === "super_admin";
      document.getElementById("changePasswordArea").style.display = isSuper ? "none" : "block";
      document.getElementById("superPasswordHint").style.display = isSuper ? "block" : "none";
    }

    async function changeOwnPassword() {
      const old_password = document.getElementById("oldPassword").value;
      const new_password = document.getElementById("newPassword").value;
      const confirmPassword = document.getElementById("confirmPassword").value;
      if (!old_password || !new_password) return showStatus("请完整填写密码");
      if (new_password !== confirmPassword) return showStatus("两次输入的新密码不一致");
      const data = await api("/api/auth/change-password", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({old_password, new_password})
      });
      alert(data.message || "密码修改成功，请重新登录");
      window.location.href = "/login";
    }

    async function loadAdminUsers() {
      const data = await api("/api/admin/users");
      document.getElementById("adminUserRows").innerHTML = data.users.map(user => {
        const role = user.role === "super_admin" ? "超级管理员" : "管理员";
        const actions = user.protected
          ? `<span class="hint">受保护账号</span>`
          : `<button class="secondary" onclick="editAdminUser(${user.id})">修改</button>
             <button class="danger" onclick="deleteAdminUser(${user.id})">删除</button>`;
        return `<tr><td>${htmlEscape(user.username)}</td><td>${htmlEscape(user.display_name || "")}</td>
          <td>${role}</td><td>${user.is_active ? "是" : "否"}</td><td>${user.is_builtin ? "是" : "否"}</td>
          <td>${htmlEscape(user.last_login_at || "")}</td><td>${actions}</td></tr>`;
      }).join("") || `<tr><td colspan="7">暂无用户</td></tr>`;
    }

    async function createAdminUser() {
      const username = document.getElementById("newAdminUsername").value.trim();
      const display_name = document.getElementById("newAdminDisplayName").value.trim();
      const password = document.getElementById("newAdminPassword").value;
      if (!username || !password) return showStatus("用户名和初始密码不能为空");
      await api("/api/admin/users", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({username, display_name, password})
      });
      document.getElementById("newAdminUsername").value = "";
      document.getElementById("newAdminDisplayName").value = "";
      document.getElementById("newAdminPassword").value = "";
      showStatus("管理员已创建");
      await loadAdminUsers();
    }

    async function editAdminUser(userId) {
      const data = await api("/api/admin/users");
      const user = data.users.find(item => item.id === userId);
      if (!user || user.protected) return showStatus("超级管理员账号受保护");
      const username = prompt("用户名", user.username);
      if (!username) return;
      const display_name = prompt("显示名称", user.display_name || "");
      if (display_name === null) return;
      const is_active = confirm("点击“确定”保持启用；点击“取消”将禁用该账号");
      await api(`/api/admin/users/${userId}`, {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({username, display_name, is_active})
      });
      showStatus("用户已更新");
      await loadAdminUsers();
    }

    async function deleteAdminUser(userId) {
      if (!confirm("确定删除这个普通管理员账号吗？")) return;
      await api(`/api/admin/users/${userId}`, {method: "DELETE"});
      showStatus("用户已删除");
      await loadAdminUsers();
    }

    async function loadLoginLogs() {
      const data = await api("/api/admin/login-logs?limit=100");
      document.getElementById("loginLogRows").innerHTML = data.records.map(row =>
        `<tr><td>${htmlEscape(row.created_at || "")}</td><td>${htmlEscape(row.username || "")}</td>
          <td>${htmlEscape(row.role || "")}</td><td>${htmlEscape(row.ip_address || "")}</td>
          <td>${row.success ? "成功" : "失败"}</td><td>${htmlEscape(row.message || "")}</td></tr>`
      ).join("") || `<tr><td colspan="6">暂无日志</td></tr>`;
    }

    async function startAdminPage() {
      await loadCurrentUser();
      await refreshAll();
      await Promise.all([
        refreshClientReleases().catch(() => {}),
        refreshClientUpdateLogs().catch(() => {}),
        loadAdminUsers().catch(() => {}),
        loadLoginLogs().catch(() => {})
      ]);
    }

    startAdminPage().catch(err => showStatus(err.message));
  </script>
</body>
</html>
"""
