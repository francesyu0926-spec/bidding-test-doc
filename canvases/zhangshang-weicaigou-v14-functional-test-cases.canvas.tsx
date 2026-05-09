import { Card, CardBody, CardHeader, Divider, Grid, H1, H2, Pill, Row, Stack, Stat, Table, Text } from "cursor/canvas";

type CaseRow = {
  id: string;
  module: string;
  scene: string;
  precondition: string;
  steps: string;
  expected: string;
  priority: "P0" | "P1" | "P2";
  type: "positive" | "negative" | "boundary";
  coverage: string;
};

const rows: CaseRow[] = [];

function add(row: CaseRow) {
  rows.push(row);
}

function batch(
  module: string,
  prefix: string,
  items: Array<Omit<CaseRow, "id" | "module">>,
) {
  items.forEach((item, i) => {
    add({
      id: `${prefix}-${String(i + 1).padStart(3, "0")}`,
      module,
      ...item,
    });
  });
}

batch("账号与身份", "ACC", [
  { scene: "微信授权登录成功", precondition: "未登录且微信授权可用", steps: "进入我的-点击登录-同意微信授权", expected: "登录成功进入已登录态", priority: "P0", type: "positive", coverage: "登录主流程" },
  { scene: "拒绝微信授权登录", precondition: "未登录", steps: "进入登录并拒绝微信授权", expected: "保持未登录并提示需授权", priority: "P0", type: "negative", coverage: "授权拒绝分支" },
  { scene: "首次登录未绑定手机号触发绑定", precondition: "微信已授权但账号未绑定手机号", steps: "完成微信授权后进入系统", expected: "自动跳转手机号绑定页", priority: "P1", type: "positive", coverage: "绑定引导" },
  { scene: "已绑定手机号直接登录", precondition: "微信账号已绑定手机号", steps: "进入我的并执行微信授权登录", expected: "直接进入系统主页无需二次绑定", priority: "P1", type: "positive", coverage: "绑定状态分支" },
  { scene: "手机号为空提交绑定", precondition: "处于手机号绑定页", steps: "不输入手机号直接提交", expected: "提示手机号必填", priority: "P1", type: "boundary", coverage: "必填校验" },
  { scene: "手机号格式错误", precondition: "处于手机号绑定页", steps: "输入非法手机号后提交", expected: "提示手机号格式错误", priority: "P1", type: "boundary", coverage: "格式校验" },
  { scene: "绑定手机号已被其他账号占用", precondition: "处于手机号绑定页且该手机号已占用", steps: "输入已占用手机号提交绑定", expected: "绑定失败并提示手机号已存在", priority: "P2", type: "negative", coverage: "唯一性校验" },
  { scene: "微信登录态失效重新授权", precondition: "历史登录过但微信会话已失效", steps: "进入我的触发登录并重新授权", expected: "授权成功后恢复登录态", priority: "P1", type: "negative", coverage: "会话时效" },
  { scene: "未登录点击我的受限入口", precondition: "未登录", steps: "点击我的中受限功能入口", expected: "弹出登录引导弹窗", priority: "P1", type: "positive", coverage: "登录拦截" },
  { scene: "多角色账号身份切换成功", precondition: "账号具备2个及以上角色", steps: "我的-身份切换-选择新角色", expected: "切换成功并展示新角色菜单", priority: "P0", type: "positive", coverage: "身份切换" },
  { scene: "单角色账号进入切换", precondition: "账号仅单角色", steps: "点击身份切换", expected: "不可切换或仅展示当前角色", priority: "P1", type: "boundary", coverage: "角色边界" },
  { scene: "切换后权限即时生效", precondition: "账号多角色", steps: "切换角色后访问新角色专属功能", expected: "可访问新角色权限功能", priority: "P0", type: "positive", coverage: "权限一致性" },
  { scene: "后台会员管理编辑角色", precondition: "管理员登录后台", steps: "会员管理编辑账号角色并保存", expected: "保存成功且小程序侧同步生效", priority: "P0", type: "positive", coverage: "后台-前台联动" },
  { scene: "后台角色编辑取消不生效", precondition: "管理员进入编辑弹窗", steps: "修改后点击取消", expected: "账号角色保持不变", priority: "P2", type: "negative", coverage: "取消动作" },
  { scene: "无权限用户访问后台会员管理", precondition: "普通账号登录后台", steps: "尝试进入会员管理页", expected: "无权限提示或拒绝访问", priority: "P0", type: "negative", coverage: "访问控制" },
  { scene: "身份切换后返回首页状态正确", precondition: "多角色账号切换成功", steps: "切换后回首页刷新", expected: "首页数据与新角色一致", priority: "P1", type: "positive", coverage: "会话一致性" },
  { scene: "登录后会话持久化", precondition: "首次成功登录", steps: "关闭并重进小程序", expected: "仍为登录态或按策略要求保持", priority: "P2", type: "positive", coverage: "会话策略" },
  { scene: "退出登录后身份清除", precondition: "已登录多角色账号", steps: "退出登录再访问我的功能", expected: "回到未登录态并触发登录引导", priority: "P1", type: "positive", coverage: "退出流程" },
]);

batch("招标人管理", "INV", [
  { scene: "项目经理发起招标人邀请成功", precondition: "项目经理已登录", steps: "招标人管理-发起邀请-填写并发送", expected: "邀请记录生成且状态待处理", priority: "P0", type: "positive", coverage: "邀请主流程" },
  { scene: "邀请必填项缺失提交", precondition: "发起邀请页", steps: "姓名或手机号为空提交", expected: "提示必填并阻止提交", priority: "P1", type: "boundary", coverage: "必填校验" },
  { scene: "被邀请手机号格式非法", precondition: "发起邀请页", steps: "输入非法手机号提交", expected: "提示手机号格式错误", priority: "P1", type: "boundary", coverage: "格式校验" },
  { scene: "邀请列表按待处理筛选", precondition: "存在多状态邀请", steps: "切换待处理标签", expected: "仅展示待处理记录", priority: "P1", type: "positive", coverage: "状态筛选" },
  { scene: "邀请列表按已接受筛选", precondition: "存在已接受记录", steps: "切换已接受标签", expected: "仅展示已接受记录", priority: "P1", type: "positive", coverage: "状态筛选" },
  { scene: "邀请列表按已拒绝筛选", precondition: "存在已拒绝记录", steps: "切换已拒绝标签", expected: "仅展示已拒绝记录", priority: "P1", type: "positive", coverage: "状态筛选" },
  { scene: "邀请列表关键字模糊查询命中", precondition: "有多条邀请记录", steps: "输入公司/姓名片段检索", expected: "返回匹配记录", priority: "P1", type: "positive", coverage: "模糊检索" },
  { scene: "关键字无命中", precondition: "有邀请记录", steps: "输入不存在关键字", expected: "空列表提示无数据", priority: "P2", type: "negative", coverage: "空结果展示" },
  { scene: "被邀请人查看邀请详情", precondition: "投标人收到邀请", steps: "我的-招标人邀请-查看", expected: "展示邀请信息与处理按钮", priority: "P0", type: "positive", coverage: "邀请查看" },
  { scene: "被邀请人接受邀请", precondition: "有待处理邀请", steps: "点击接受", expected: "状态变已接受并新增招标人权限", priority: "P0", type: "positive", coverage: "接受分支" },
  { scene: "被邀请人拒绝邀请", precondition: "有待处理邀请", steps: "点击拒绝", expected: "状态变已拒绝且角色不变", priority: "P0", type: "positive", coverage: "拒绝分支" },
  { scene: "已处理邀请重复处理", precondition: "邀请已接受/已拒绝", steps: "再次进入详情尝试处理", expected: "按钮禁用或禁止重复处理", priority: "P1", type: "negative", coverage: "幂等性" },
  { scene: "发起人与接收人状态同步", precondition: "邀请已被处理", steps: "发起端刷新列表", expected: "发起端状态与接收端一致", priority: "P1", type: "positive", coverage: "双端一致性" },
  { scene: "邀请记录按时间倒序", precondition: "多条邀请记录", steps: "进入邀请列表观察排序", expected: "默认按发起时间倒序", priority: "P2", type: "boundary", coverage: "排序规则" },
]);

batch("专家申请与资料", "EXP", [
  { scene: "申请成为专家提交成功", precondition: "投标人或项目经理登录", steps: "我的-申请成为专家-填资料-提交", expected: "申请进入待审核状态", priority: "P0", type: "positive", coverage: "申请主流程" },
  { scene: "申请资料缺失提交", precondition: "申请页面可用", steps: "不填关键字段直接提交", expected: "提示必填并阻止提交", priority: "P1", type: "boundary", coverage: "必填校验" },
  { scene: "证件附件格式非法", precondition: "申请页面可用", steps: "上传不支持格式附件", expected: "上传失败并提示支持格式", priority: "P1", type: "negative", coverage: "上传校验" },
  { scene: "重复发起专家申请", precondition: "存在待审核申请", steps: "再次进入申请并提交", expected: "提示申请处理中不可重复提交", priority: "P1", type: "negative", coverage: "重复提交" },
  { scene: "后台审核通过", precondition: "后台有待审核专家申请", steps: "审核通过该申请", expected: "账号新增专家角色", priority: "P0", type: "positive", coverage: "审核通过分支" },
  { scene: "后台审核驳回", precondition: "后台有待审核专家申请", steps: "审核驳回并填写原因", expected: "用户侧显示驳回状态和原因", priority: "P1", type: "positive", coverage: "审核驳回分支" },
  { scene: "专家资料修改提交", precondition: "专家账号已登录", steps: "资料管理修改信息后提交", expected: "进入待审核，原信息暂不生效", priority: "P0", type: "positive", coverage: "资料修改流程" },
  { scene: "专家签名上传并提交", precondition: "专家账号已登录", steps: "上传签名并保存", expected: "提交成功进入待审核", priority: "P0", type: "positive", coverage: "签名流程" },
  { scene: "签名尺寸过大边界", precondition: "签名上传入口可用", steps: "上传超大小文件", expected: "提示超限并拒绝", priority: "P2", type: "boundary", coverage: "文件大小边界" },
  { scene: "资料审核通过后生效", precondition: "存在待审资料修改", steps: "后台通过审核", expected: "新资料在专家端与评标签名环节可见", priority: "P1", type: "positive", coverage: "生效机制" },
  { scene: "资料审核驳回后回退", precondition: "存在待审资料修改", steps: "后台驳回", expected: "继续沿用旧资料并展示驳回反馈", priority: "P1", type: "positive", coverage: "回退机制" },
  { scene: "无专家角色访问资料管理", precondition: "普通投标人登录", steps: "访问专家资料管理入口", expected: "入口不可见或无权限", priority: "P1", type: "negative", coverage: "权限控制" },
]);

batch("招标发布", "PUB", [
  { scene: "项目经理新建项目成功", precondition: "项目经理已登录", steps: "公告发布完整填写并新建", expected: "项目发布成功且在招标公告可见", priority: "P0", type: "positive", coverage: "发布主流程" },
  { scene: "未选择招标方提交", precondition: "新建项目页", steps: "缺失招标方后提交", expected: "提示招标方必选", priority: "P0", type: "boundary", coverage: "必填校验" },
  { scene: "未选择招标方式提交", precondition: "新建项目页", steps: "不选招标方式提交", expected: "提示招标方式必选", priority: "P0", type: "boundary", coverage: "必填校验" },
  { scene: "文件费与平台使用费分开填写", precondition: "新建项目页", steps: "分别输入两项费用并保存", expected: "两项独立展示并参与后续分项缴费", priority: "P0", type: "positive", coverage: "费用拆分" },
  { scene: "文件费为0边界", precondition: "新建项目页", steps: "文件费输入0提交", expected: "按规则允许或提示最小值限制", priority: "P2", type: "boundary", coverage: "金额边界" },
  { scene: "平台使用费负数输入", precondition: "新建项目页", steps: "输入负数费用提交", expected: "拦截并提示金额非法", priority: "P1", type: "negative", coverage: "金额合法性" },
  { scene: "开标时间早于当前时间", precondition: "新建项目页", steps: "设置过去时间并提交", expected: "提示开标时间无效", priority: "P1", type: "boundary", coverage: "时间边界" },
  { scene: "文件获取开始晚于结束", precondition: "新建项目页", steps: "设置开始时间>结束时间提交", expected: "提示时间区间非法", priority: "P1", type: "boundary", coverage: "时序校验" },
  { scene: "获取采购文件是否审核=是", precondition: "项目发布配置为是", steps: "投标人报名后查看状态", expected: "进入待审核流程", priority: "P0", type: "positive", coverage: "流程分支A" },
  { scene: "获取采购文件是否审核=否", precondition: "项目发布配置为否", steps: "投标人报名后查看状态", expected: "直接进入待缴费流程", priority: "P0", type: "positive", coverage: "流程分支B" },
  { scene: "是否公开报名信息=是", precondition: "发布时选择公开", steps: "进入项目详情查看报名单位信息", expected: "可见报名信息", priority: "P1", type: "positive", coverage: "展示分支" },
  { scene: "是否公开报名信息=否", precondition: "发布时选择不公开", steps: "进入项目详情查看报名单位信息", expected: "报名信息隐藏", priority: "P1", type: "positive", coverage: "展示分支" },
  { scene: "报价评分方法一-情况1 n>3", precondition: "编辑评审表格报价评分", steps: "设置方法一情况1并输入n=5保存", expected: "保存成功", priority: "P1", type: "positive", coverage: "评分配置" },
  { scene: "报价评分方法一-情况1 n=3", precondition: "编辑评审表格报价评分", steps: "输入n=3提交", expected: "提示n必须大于3", priority: "P1", type: "boundary", coverage: "评分边界" },
  { scene: "报价评分方法一-情况2", precondition: "编辑评审表格", steps: "选择所有合格供应商平均值策略", expected: "保存成功并进入对应计算策略", priority: "P1", type: "positive", coverage: "评分分支" },
  { scene: "报价评分方法二", precondition: "编辑评审表格", steps: "选择最低价为基准价策略", expected: "保存成功并后续自动计算", priority: "P1", type: "positive", coverage: "评分分支" },
  { scene: "报价评分方法三手动录入", precondition: "编辑评审表格", steps: "选择手动输入分值策略", expected: "后续报价阶段由组长手工录入", priority: "P1", type: "positive", coverage: "评分分支" },
  { scene: "是否最低价中标=是触发流程变更", precondition: "发布项目时勾选最低价中标", steps: "开评标后观察流程节点", expected: "流程按最低价中标规则展示", priority: "P0", type: "positive", coverage: "流程分支C" },
  { scene: "项目发布后在公告可检索", precondition: "项目发布成功", steps: "招标公告输入关键字检索", expected: "可命中新发布项目", priority: "P2", type: "positive", coverage: "发布结果验证" },
  { scene: "编辑评审表格后保存回显", precondition: "投标中项目可编辑评审表格", steps: "修改评分项并保存后重进", expected: "字段与内容正确回显", priority: "P1", type: "positive", coverage: "数据持久化" },
  { scene: "已到开标时间后不可修改时间", precondition: "项目已达开标时间", steps: "发布变更尝试修改时间节点", expected: "禁止修改并提示原因", priority: "P0", type: "negative", coverage: "状态门禁" },
  { scene: "招标方式与后续流程映射正确", precondition: "分别创建不同招标方式项目", steps: "进入开评标查看流程", expected: "流程节点与招标方式定义一致", priority: "P0", type: "positive", coverage: "流程映射" },
]);

batch("投标报名与审核", "REG", [
  { scene: "投标人提交报名成功", precondition: "项目在报名时间内", steps: "获取文件-填报名信息-上传并提交", expected: "报名记录生成", priority: "P0", type: "positive", coverage: "报名主流程" },
  { scene: "报名缺失必填项", precondition: "报名页面可用", steps: "不填关键字段提交", expected: "提示必填并阻止提交", priority: "P1", type: "boundary", coverage: "必填校验" },
  { scene: "报名文件未上传", precondition: "报名页面可用", steps: "不上传文件直接提交", expected: "提示需上传报名文件", priority: "P1", type: "boundary", coverage: "上传必填" },
  { scene: "报名超出文件获取结束时间", precondition: "项目已过获取结束时间", steps: "尝试报名提交", expected: "禁止报名并提示已截止", priority: "P0", type: "negative", coverage: "时间门禁" },
  { scene: "我的报名展示状态待审核", precondition: "项目需审核且已提交报名", steps: "进入我的报名列表", expected: "状态显示待审核", priority: "P1", type: "positive", coverage: "状态展示" },
  { scene: "我的报名展示状态待缴费", precondition: "报名审核通过", steps: "进入我的报名列表", expected: "状态显示待缴费", priority: "P1", type: "positive", coverage: "状态展示" },
  { scene: "我的报名展示状态已完成", precondition: "报名已完成全部缴费", steps: "进入我的报名列表", expected: "状态显示已完成", priority: "P1", type: "positive", coverage: "状态展示" },
  { scene: "待审核状态取消报名确认", precondition: "项目处于待审核", steps: "点击取消报名-确认", expected: "取消成功并从后续流程剔除", priority: "P0", type: "positive", coverage: "取消分支" },
  { scene: "待审核状态取消报名返回", precondition: "项目处于待审核", steps: "点击取消报名-返回", expected: "状态不变", priority: "P2", type: "negative", coverage: "弹窗分支" },
  { scene: "待缴费进入缴费页", precondition: "项目处于待缴费", steps: "点击立即缴费", expected: "进入分项缴费页面", priority: "P0", type: "positive", coverage: "缴费入口" },
  { scene: "仅缴纳文件费", precondition: "待缴费状态", steps: "只完成文件费支付", expected: "仍不可下载招标文件", priority: "P0", type: "boundary", coverage: "分项完整性" },
  { scene: "仅缴纳平台使用费", precondition: "待缴费状态", steps: "只完成平台使用费支付", expected: "仍不可下载招标文件", priority: "P0", type: "boundary", coverage: "分项完整性" },
  { scene: "两项费用全部缴纳", precondition: "待缴费状态", steps: "完成两项支付", expected: "按钮显示已缴费并可下载招标文件", priority: "P0", type: "positive", coverage: "缴费完成" },
  { scene: "微信支付失败", precondition: "可调起微信支付", steps: "支付流程中取消或失败", expected: "状态不变仍待缴费", priority: "P1", type: "negative", coverage: "支付失败分支" },
  { scene: "支付成功回调幂等", precondition: "支付成功且回调可能重试", steps: "模拟重复回调", expected: "仅记一次有效支付记录", priority: "P1", type: "negative", coverage: "幂等性" },
  { scene: "下载招标文件成功", precondition: "已完成全部缴费", steps: "点击下载招标文件", expected: "可查看/下载文件", priority: "P0", type: "positive", coverage: "文件获取" },
  { scene: "未缴费尝试下载文件", precondition: "待缴费状态", steps: "点击下载招标文件", expected: "被拦截并提示需先缴费", priority: "P0", type: "negative", coverage: "门禁校验" },
  { scene: "项目经理报名审核通过", precondition: "有待审核报名", steps: "报名审核点击通过", expected: "状态变待缴费", priority: "P0", type: "positive", coverage: "审核通过" },
  { scene: "项目经理报名审核驳回", precondition: "有待审核报名", steps: "报名审核点击驳回", expected: "状态变已驳回", priority: "P0", type: "positive", coverage: "审核驳回" },
  { scene: "已驳回报名不允许递交投标文件", precondition: "报名状态已驳回", steps: "进入项目管理尝试递交", expected: "被禁止递交", priority: "P0", type: "negative", coverage: "门禁校验" },
  { scene: "取消报名后不允许递交投标文件", precondition: "报名已取消", steps: "进入项目管理尝试递交", expected: "被禁止递交", priority: "P0", type: "negative", coverage: "门禁校验" },
  { scene: "退款后不允许递交投标文件", precondition: "报名缴费后退款成功", steps: "尝试递交投标文件", expected: "被禁止递交并提示无效投标人", priority: "P0", type: "negative", coverage: "退款分支" },
  { scene: "审核列表状态分组完整", precondition: "存在待审核/已审核/待缴费/已完成/已驳回记录", steps: "逐个切换状态页签", expected: "各状态分组正确无串组", priority: "P1", type: "positive", coverage: "状态分支全覆盖" },
  { scene: "审核详情信息完整性", precondition: "有待审核报名", steps: "进入审核详情", expected: "报名字段和附件展示完整", priority: "P2", type: "positive", coverage: "详情展示" },
]);

batch("投标人项目管理", "BID", [
  { scene: "已完成报名项目进入投标中列表", precondition: "报名成功", steps: "我的-项目管理", expected: "项目在投标中展示", priority: "P0", type: "positive", coverage: "状态同步" },
  { scene: "项目列表关键字查询", precondition: "存在多个项目", steps: "输入项目关键字查询", expected: "返回匹配项目", priority: "P2", type: "positive", coverage: "检索能力" },
  { scene: "待递交状态递交投标文件成功", precondition: "投标中且可递交", steps: "上传文件并点击递交", expected: "标签变已递交", priority: "P0", type: "positive", coverage: "递交流程" },
  { scene: "递交缺少附件", precondition: "递交页面可用", steps: "不上传附件直接递交", expected: "提示附件必传", priority: "P1", type: "boundary", coverage: "必填校验" },
  { scene: "递交截止后禁止递交", precondition: "已过递交截止", steps: "尝试递交", expected: "被拦截并提示截止", priority: "P0", type: "negative", coverage: "时间门禁" },
  { scene: "已递交状态撤回成功", precondition: "已递交且未到截止", steps: "点击撤回并确认", expected: "标签变已撤回并记录时间", priority: "P0", type: "positive", coverage: "撤回分支" },
  { scene: "撤回后再次递交", precondition: "状态已撤回且未到截止", steps: "再次上传并递交", expected: "恢复为已递交", priority: "P0", type: "positive", coverage: "重复递交" },
  { scene: "已撤回记录留痕", precondition: "至少执行过一次撤回", steps: "查看项目操作记录", expected: "存在递交/撤回时间记录", priority: "P1", type: "positive", coverage: "审计记录" },
  { scene: "到开标时间进入已开标", precondition: "已递交项目临近开标", steps: "到点刷新项目状态", expected: "转为已开标", priority: "P0", type: "positive", coverage: "自动状态迁移" },
  { scene: "签字解密成功", precondition: "项目已开标且待解密", steps: "点击签字解密输入正确密码", expected: "解密成功并可供专家下载", priority: "P0", type: "positive", coverage: "解密主流程" },
  { scene: "签字解密密码错误", precondition: "项目已开标且待解密", steps: "输入错误密码", expected: "解密失败并提示密码错误", priority: "P0", type: "negative", coverage: "解密异常" },
  { scene: "评审中项目只读", precondition: "项目处于评审中", steps: "进入详情尝试操作按钮", expected: "仅可查看不可操作", priority: "P1", type: "positive", coverage: "状态权限" },
  { scene: "谈判/磋商回复成功", precondition: "组长已发起谈判/磋商", steps: "点击回复输入内容并提交", expected: "回复提交成功并可供专家查看", priority: "P0", type: "positive", coverage: "谈判分支" },
  { scene: "谈判/磋商回复附带附件", precondition: "已到回复阶段", steps: "填写回复并上传附件提交", expected: "文本与附件均保存", priority: "P1", type: "positive", coverage: "附件分支" },
  { scene: "未到回复阶段不可回复", precondition: "未收到组长发起", steps: "尝试进入回复入口", expected: "入口不可用或提示等待", priority: "P1", type: "negative", coverage: "阶段门禁" },
  { scene: "二轮报价查看要求信息", precondition: "组长已发起二轮报价", steps: "查看二轮报价信息", expected: "展示组长填写的要求", priority: "P1", type: "positive", coverage: "信息同步" },
  { scene: "二轮报价提交成功", precondition: "二轮报价阶段开放", steps: "输入报价上传附件并提交", expected: "报价记录生成且状态更新", priority: "P0", type: "positive", coverage: "二轮报价主流程" },
  { scene: "二轮报价非法金额", precondition: "二轮报价页面可用", steps: "输入负数或非数字金额提交", expected: "提示金额非法", priority: "P1", type: "boundary", coverage: "金额校验" },
  { scene: "已中标项目缴纳代理费成功", precondition: "项目状态已中标且收到代理费通知", steps: "填支付信息上传打款截图并确认", expected: "代理费支付成功记录", priority: "P0", type: "positive", coverage: "中标后流程" },
  { scene: "废标项目状态展示", precondition: "项目被废标", steps: "进入项目管理查看", expected: "在废标分组可见且不可继续投标操作", priority: "P1", type: "positive", coverage: "终态分支" },
]);

batch("项目经理项目管理", "PM", [
  { scene: "项目管理四状态展示", precondition: "存在投标中/已开标/已中标/废标项目", steps: "进入项目管理切换状态", expected: "四状态分组展示正确", priority: "P0", type: "positive", coverage: "状态总览" },
  { scene: "投标中-编辑评审表格成功", precondition: "项目处于投标中", steps: "点击编辑评审表格并保存", expected: "保存成功并影响后续评审", priority: "P0", type: "positive", coverage: "投标中操作A" },
  { scene: "投标中-发布变更成功", precondition: "项目处于投标中且未到开标时间", steps: "修改项目信息并发布变更", expected: "变更成功并按新时间生效", priority: "P0", type: "positive", coverage: "投标中操作B" },
  { scene: "投标中-已到开标时间禁止改时间", precondition: "项目已达开标时间", steps: "尝试发布变更修改时间", expected: "系统拒绝并提示原因", priority: "P0", type: "negative", coverage: "状态门禁" },
  { scene: "投标中-邀请专家成功", precondition: "专家库有可邀专家", steps: "抽取评标专家-邀请专家-提交", expected: "邀请发送成功", priority: "P0", type: "positive", coverage: "抽取专家分支A" },
  { scene: "投标中-随机抽取专家成功", precondition: "筛选条件下专家数量充足", steps: "随机抽取设置人数并确认", expected: "抽取成功并生成名单", priority: "P0", type: "positive", coverage: "抽取专家分支B" },
  { scene: "随机抽取专家人数不足", precondition: "筛选范围专家不足", steps: "设置抽取人数大于可用人数", expected: "提示人数不足", priority: "P1", type: "negative", coverage: "抽取异常" },
  { scene: "随机抽取5级专业筛选", precondition: "专家专业库完备", steps: "按多级专业筛选再抽取", expected: "仅抽到匹配专业专家", priority: "P1", type: "positive", coverage: "专业边界" },
  { scene: "已开标-查看进度流程图", precondition: "项目状态已开标", steps: "点击查看进度", expected: "展示完整流程及已完成节点", priority: "P1", type: "positive", coverage: "已开标操作A" },
  { scene: "已开标-查看形式资格响应性明细", precondition: "对应阶段已完成", steps: "点击查看评审明细", expected: "详情数据完整可读", priority: "P1", type: "positive", coverage: "已开标操作B" },
  { scene: "已开标-查看商务评分明细", precondition: "商务评分已完成", steps: "点击查看", expected: "汇总与明细可查", priority: "P1", type: "positive", coverage: "已开标操作C" },
  { scene: "已开标-查看技术评分专家明细", precondition: "技术评分已完成", steps: "切换汇总/专家明细", expected: "切换正确且数据一致", priority: "P1", type: "positive", coverage: "已开标操作D" },
  { scene: "已开标-查看谈判/磋商与二轮报价", precondition: "项目走谈判或二轮流程", steps: "点击查看对应信息", expected: "展示发起内容与回复结果", priority: "P1", type: "positive", coverage: "已开标操作E" },
  { scene: "已开标-查看报价评分明细", precondition: "报价评分已完成", steps: "点击查看报价评分", expected: "展示评分结果与计算/录入值", priority: "P1", type: "positive", coverage: "已开标操作F" },
  { scene: "已开标-查看最终得分与候选人", precondition: "评审完成", steps: "进入最终得分/候选人页面", expected: "排名与候选人信息正确", priority: "P0", type: "positive", coverage: "已开标操作G" },
  { scene: "评标报告自动生成并可编辑", precondition: "评审完成", steps: "进入评标报告页面编辑保存", expected: "报告可编辑保存", priority: "P0", type: "positive", coverage: "报告流程A" },
  { scene: "评标报告推送后不可编辑", precondition: "报告已推送专家", steps: "尝试再次编辑", expected: "编辑按钮置灰", priority: "P0", type: "negative", coverage: "报告流程B" },
  { scene: "专家退回后报告可再次编辑", precondition: "报告已被专家退回", steps: "项目经理进入报告页", expected: "编辑能力恢复", priority: "P1", type: "positive", coverage: "报告流程C" },
  { scene: "发布中标公示成功", precondition: "已产生中标候选人", steps: "填写中标单位与公示内容并发布", expected: "中标公告发布成功", priority: "P0", type: "positive", coverage: "中标公示" },
  { scene: "推送代理费-标准计费", precondition: "中标公示已发布", steps: "选择标准计费并输入折扣后推送", expected: "中标单位收到缴费通知", priority: "P0", type: "positive", coverage: "代理费分支A" },
  { scene: "推送代理费-固定收费", precondition: "中标公示已发布", steps: "选择固定收费输入金额并推送", expected: "通知成功下发", priority: "P0", type: "positive", coverage: "代理费分支B" },
  { scene: "已推送代理费可修改重推", precondition: "代理费已推送过", steps: "点击修改调整费用再推送", expected: "新费用生效并覆盖旧通知", priority: "P1", type: "positive", coverage: "代理费修改" },
  { scene: "开标表格一键导出PDF", precondition: "评标已完成", steps: "点击导出开标表格", expected: "成功下载PDF文件", priority: "P0", type: "positive", coverage: "导出能力" },
]);

batch("专家评审管理", "REV", [
  { scene: "待确认-专家同意邀请", precondition: "专家收到项目邀请", steps: "首页待确认点击同意", expected: "项目进入未开标或评审阶段待处理", priority: "P0", type: "positive", coverage: "确认分支A" },
  { scene: "待确认-专家拒绝邀请", precondition: "专家收到项目邀请", steps: "点击拒绝", expected: "项目不进入其评审任务", priority: "P1", type: "positive", coverage: "确认分支B" },
  { scene: "未开标列表展示", precondition: "专家已同意邀请且未到开标时间", steps: "进入未开标列表", expected: "可见对应项目", priority: "P1", type: "positive", coverage: "状态展示" },
  { scene: "到开标时间进入评审中", precondition: "项目已到开标时间", steps: "刷新首页状态", expected: "项目转评审中", priority: "P0", type: "positive", coverage: "状态迁移" },
  { scene: "开始签到并阅读承诺书完成", precondition: "项目评审中且待签到", steps: "开始签到-阅读-下一步/完成", expected: "签到成功", priority: "P0", type: "positive", coverage: "签到流程" },
  { scene: "未签到前禁止后续评审", precondition: "项目评审中未签到", steps: "尝试进入后续评审按钮", expected: "被拦截并提示先签到", priority: "P1", type: "negative", coverage: "阶段门禁" },
  { scene: "资料下载成功", precondition: "专家已签到", steps: "文件下载-资料下载", expected: "可下载招标与投标文件", priority: "P0", type: "positive", coverage: "资料下载" },
  { scene: "组长推选成功", precondition: "全部专家已签到", steps: "选择候选组长并提交", expected: "产生组长且下一步按钮亮起", priority: "P0", type: "positive", coverage: "组长推选" },
  { scene: "组长推选平票重投", precondition: "存在平票场景", steps: "提交投票产生平票", expected: "提示平票并要求重新投票", priority: "P0", type: "negative", coverage: "平票分支" },
  { scene: "形式评审通过分支", precondition: "完成组长推选", steps: "形式评审选择符合并下一步", expected: "进入资格评审", priority: "P1", type: "positive", coverage: "评审阶段A" },
  { scene: "资格评审不通过分支", precondition: "进入资格评审", steps: "选择不符合并提交", expected: "结果记录并影响后续候选", priority: "P1", type: "positive", coverage: "评审阶段B" },
  { scene: "响应性评审通过分支", precondition: "进入响应性评审", steps: "选择符合并提交", expected: "可进入后续阶段", priority: "P1", type: "positive", coverage: "评审阶段C" },
  { scene: "三项评审意见不一致阻塞", precondition: "多位专家评分意见不一致", steps: "最后一位专家点击下一步", expected: "提示需项目经理核对统一并阻塞流程", priority: "P0", type: "negative", coverage: "一致性门禁" },
  { scene: "谈判/磋商由组长发起成功", precondition: "项目招标方式包含谈判/磋商", steps: "组长填写内容并发起", expected: "投标人端收到回复任务", priority: "P0", type: "positive", coverage: "谈判流程" },
  { scene: "组员在组长发起前只读等待", precondition: "处于谈判阶段且未发起", steps: "组员进入页面", expected: "仅可等待不可发起", priority: "P1", type: "positive", coverage: "角色权限" },
  { scene: "专家查看投标人谈判回复", precondition: "投标人已/未回复混合", steps: "查看回复列表", expected: "未回复显示等待，已回复可查看详情", priority: "P1", type: "positive", coverage: "回复状态分支" },
  { scene: "二轮报价由组长发起成功", precondition: "进入二轮报价阶段", steps: "组长发起二轮报价", expected: "投标人收到报价任务", priority: "P0", type: "positive", coverage: "二轮流程" },
  { scene: "专家查看二轮报价回复状态", precondition: "部分投标人已报价", steps: "查看二轮报价列表", expected: "未提供/查看状态正确", priority: "P1", type: "positive", coverage: "二轮状态分支" },
  { scene: "商务评分仅组长可录入", precondition: "进入商务评分阶段", steps: "组长和组员分别查看页面", expected: "组长可评分组员只读", priority: "P0", type: "positive", coverage: "角色权限" },
  { scene: "技术评分专家独立打分", precondition: "进入技术评分阶段", steps: "多位专家分别打分并提交", expected: "分值独立记录", priority: "P0", type: "positive", coverage: "评分机制" },
  { scene: "报价评分-方法一/二自动计算可改", precondition: "项目配置公示计分", steps: "进入报价评分查看自动分并由组长修改后提交", expected: "组长可修改，组员只读", priority: "P0", type: "positive", coverage: "报价评分分支A/B" },
  { scene: "报价评分-方法三手工录入", precondition: "项目配置手工计分", steps: "组长手工录入报价分并提交", expected: "录入成功并进入下一步", priority: "P0", type: "positive", coverage: "报价评分分支C" },
  { scene: "开标表格查看与一键签名", precondition: "评标报告状态已生成", steps: "专家查看开标表格并一键签名", expected: "全部文件完成签名", priority: "P0", type: "positive", coverage: "签章流程" },
  { scene: "评标报告签名退回分支", precondition: "项目经理已推送评标报告", steps: "专家点击退回", expected: "报告退回项目经理并待修改重推", priority: "P1", type: "positive", coverage: "退回分支" },
]);

const typeCount = rows.reduce(
  (acc, r) => {
    acc[r.type] += 1;
    return acc;
  },
  { positive: 0, negative: 0, boundary: 0 },
);

const pCount = rows.reduce(
  (acc, r) => {
    acc[r.priority] += 1;
    return acc;
  },
  { P0: 0, P1: 0, P2: 0 },
);

const moduleCountMap = rows.reduce<Record<string, number>>((acc, r) => {
  acc[r.module] = (acc[r.module] || 0) + 1;
  return acc;
}, {});

const moduleRows = Object.entries(moduleCountMap).map(([name, count]) => [name, String(count)]);

const tableRows = rows.map((r) => [
  r.id,
  r.module,
  r.scene,
  r.precondition,
  r.steps,
  r.expected,
  r.priority,
  r.type,
  r.coverage,
]);

export default function FunctionalTestCasesCanvas() {
  return (
    <Stack gap={18}>
      <H1>掌上微采购（三期）v1.4 功能测试用例全集</H1>
      <Text tone="secondary">
        覆盖账号、招标人、专家、发布、报名、审核、投标、开评标与签章闭环，包含正向、异常、边界和关键状态流转分支。
      </Text>

      <Grid columns={4} gap={12}>
        <Stat label="用例总数" value={String(rows.length)} />
        <Stat label="P0 / P1 / P2" value={`${pCount.P0} / ${pCount.P1} / ${pCount.P2}`} />
        <Stat label="正向 / 异常 / 边界" value={`${typeCount.positive} / ${typeCount.negative} / ${typeCount.boundary}`} />
        <Stat label="模块数" value={String(Object.keys(moduleCountMap).length)} />
      </Grid>

      <Row gap={8}>
        <Pill tone="info">状态流转覆盖</Pill>
        <Pill tone="info">角色权限覆盖</Pill>
        <Pill tone="info">时间边界覆盖</Pill>
        <Pill tone="info">金额边界覆盖</Pill>
      </Row>

      <Divider />

      <H2>模块分布</H2>
      <Table headers={["模块", "用例数"]} rows={moduleRows} />

      <Divider />

      <Card>
        <CardHeader title="完整测试用例清单（可直接用于执行）" subtitle="字段：编号、模块、场景、前置条件、步骤、预期、优先级、类型、覆盖点" />
        <CardBody style={{ padding: 0 }}>
          <Table
            headers={["编号", "模块", "场景", "前置条件", "步骤", "预期结果", "优先级", "类型", "覆盖点"]}
            rows={tableRows}
          />
        </CardBody>
      </Card>
    </Stack>
  );
}
