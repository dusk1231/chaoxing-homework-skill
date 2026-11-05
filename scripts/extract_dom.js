/* extract_dom.js — 在作业页 DevTools 控制台执行，把整页题目提取成 questions.json 结构。
   结果通过 copy() 写回剪贴板，再用 clip.ps1 get 落盘。
   输出 schema 与 parse_work_html.py 一致，可直接喂给 make_fill_js.py。
   注意：本文件会被 clip.ps1 压成单行，所以只能用块注释，不能出现行注释。 */
(function () {
  var qs = document.querySelectorAll('.questionLi');
  var out = [];
  for (var i = 0; i < qs.length; i++) {
    var q = qs[i];
    var qid = q.getAttribute('data') || (q.id || '').replace('question', '');
    var typeName = (q.getAttribute('typeName') || '').trim();
    var h3 = q.querySelector('h3');
    var stem = h3 ? h3.innerText.replace(/\s+/g, ' ').trim() : '';

    var opts = [];
    var boxes = q.querySelectorAll('.answerBg, .answerBgDx');
    for (var j = 0; j < boxes.length; j++) {
      var b = boxes[j];
      var sp = b.querySelector('[data]');
      var data = sp ? sp.getAttribute('data') : '';
      var letter = sp ? (sp.innerText || '').replace(/\s+/g, '').trim() : '';
      var txt = (b.innerText || '').replace(/\s+/g, ' ').trim();
      if (letter && txt.indexOf(letter) === 0) { txt = txt.slice(letter.length).trim(); }
      var imgs = [];
      var im = b.querySelectorAll('img');
      for (var m = 0; m < im.length; m++) { if (im[m].src) { imgs.push(im[m].src); } }
      opts.push({ letter: letter, data: data, text: txt, imgs: imgs });
    }

    var fillEds = [];
    var essayEd = null;
    var tas = q.querySelectorAll('textarea');
    for (var t = 0; t < tas.length; t++) {
      var id = tas[t].id || '';
      if (/^answerEditor/.test(id)) { fillEds.push(id); }
      else if (/^answer/.test(id)) { essayEd = id; }
    }

    var blanks = 0;
    var bs = q.querySelector('input[name="tiankongsize' + qid + '"]');
    if (bs) { blanks = parseInt(bs.value || '0', 10) || 0; }

    var multi = !!q.querySelector('.num_option_dx');
    var kind = 'choice';
    if (fillEds.length) { kind = 'fill'; }
    else if (essayEd) { kind = 'essay'; }

    var qtype = 0;
    if (kind === 'fill') { qtype = 2; }
    else if (kind === 'essay') { qtype = 4; }
    else if (typeName.indexOf('判断') >= 0) { qtype = 3; }

    out.push({
      num: i + 1,
      qid: qid,
      type: typeName,
      qtype: qtype,
      kind: kind,
      multiple: multi,
      stem: stem,
      options: opts,
      editor: essayEd,
      editors: fillEds,
      blanks: blanks,
      answer_field: 'answer' + qid
    });
  }
  copy(JSON.stringify({ ok: true, count: out.length, questions: out }));
  return 'EXTRACT ' + out.length;
})()
