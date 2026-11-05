/* submit.js — 学习通 dowork 页「提交」+「确认弹窗」一次做完（R2 通道用）
   用法: node cdp.mjs eval --file submit.js --shot submit.png
   返回: SUBMITTED <按钮文本> / SUBMITTED_PAGE / ALREADY_DONE / NO_SUBMIT_BUTTON / CONFIRM_TIMEOUT
   原则: 只点「提交/确定/确认/是」，绝不点「取消/关闭」；已经是分数页就直接返回。
   注意: 只在**最内层**匹配按钮（父容器的 innerText 也含同样文字，点到容器上是空操作甚至误触发）。 */
(async function () {
  var sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  function T(el) { return (el.innerText || el.value || '').replace(/\s+/g, ' ').trim(); }
  function visible(el) { return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length); }
  function findByText(re, scope) {
    scope = scope || document;
    var all = scope.querySelectorAll('button,a,div,span,input[type=button],input[type=submit],li');
    var hits = [];
    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      if (!visible(el)) { continue; }
      var t = T(el);
      if (t && t.length <= 12 && re.test(t)) { hits.push(el); }
    }
    var inner = [];
    for (var k = 0; k < hits.length; k++) {
      var el = hits[k], covered = false;
      for (var j = 0; j < hits.length; j++) {
        if (j !== k && hits[j] !== el && el.contains(hits[j])) { covered = true; break; }
      }
      if (!covered) { inner.push(el); }
    }
    return inner;
  }

  if (/分数|查看详情/.test(document.body.innerText)) { return 'ALREADY_DONE'; }

  var btn = findByText(/^(提交|提交作业|交卷)$/);
  if (!btn.length) { return 'NO_SUBMIT_BUTTON'; }
  btn[0].scrollIntoView({ block: 'center' });
  btn[0].click();

  for (var i = 0; i < 48; i++) {
    await sleep(250);
    var dlg = document.querySelector('.layui-layer-btn, .layer-btn, .popup, .dialog, .maskDiv, .confirm');
    var scope = document;
    if (dlg) { scope = dlg.closest('.layui-layer') || dlg.parentElement || document; }
    var yes = findByText(/^(确定|确认|提交|是|是的)$/, scope);
    for (var k = 0; k < yes.length; k++) {
      if (yes[k] !== btn[0]) {
        yes[k].click();
        return 'SUBMITTED ' + T(yes[k]);
      }
    }
    if (/分数|查看详情/.test(document.body.innerText)) { return 'SUBMITTED_PAGE'; }
  }
  return 'CONFIRM_TIMEOUT';
})()
