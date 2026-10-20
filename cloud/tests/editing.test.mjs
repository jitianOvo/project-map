import test from 'node:test';
import assert from 'node:assert/strict';
import {wrap,indent,heading,numberedEnter,insertVersion,removeVersion} from '../web/editing.js';
import {accepted,documentMerge,fields} from '../web/core.js';

const apply=(text,edit)=>text.slice(0,edit.start)+edit.replacement+text.slice(edit.end);
test('加粗包含两侧符号或只选内部都能取消',()=>{
  assert.equal(apply('**测试**',wrap('**测试**',0,6,'**')),'测试');
  assert.equal(apply('**测试**',wrap('**测试**',2,4,'**')),'测试');
  assert.equal(apply('这一行',wrap('这一行',1,1,'**')),'**这一行**');
});
test('批量 Tab 纠正优先、再次缩进、Shift Tab 混合取消',()=>{
  const text='1.不规范\n2. 正常\n其他';
  const fixed=apply(text,indent(text,0,text.length));
  assert.equal(fixed,'1. 不规范\n2. 正常\n其他');
  assert.equal(apply(fixed,indent(fixed,0,fixed.length)),'\t1. 不规范\n\t2. 正常\n\t其他');
  const mixed='\t缩进\n没有缩进\n\t其他';
  assert.equal(apply(mixed,indent(mixed,0,mixed.length,true)),'缩进\n没有缩进\n其他');
});
test('标准序号单行续号、Shift Enter 插入并重排',()=>{
  assert.equal(apply('1. 内容',numberedEnter('1. 内容',5,5)),'1. 内容\n2. ');
  assert.equal(numberedEnter('1.内容',4,4),null);
  const text='1. 第一\n2. 第二\n3. 第三\n4. 第四';
  const position=text.indexOf('\n3.');
  assert.equal(apply(text,numberedEnter(text,position,position,true)),'1. 第一\n2. 第二\n3. \n4. 第三\n5. 第四');
});
test('标题替换、再次取消',()=>{
  assert.equal(apply('# 标题',heading('# 标题',2,2,2)),'## 标题');
  assert.equal(apply('## 标题',heading('## 标题',3,3,2)),'标题');
});
test('版本加塞和删除后的编号修正',()=>{
  const text='# V1\n内容\n# V2\n内容';const pos=text.indexOf('# V2');
  const added=apply(text,insertVersion(text,pos,pos));
  assert.match(added,/# V2\n\n# V3/);
  assert.equal(apply(added,removeVersion(added,added.indexOf('# V2'),added.indexOf('# V2'))),text.replace('# V2','# V2').replace('内容\n# V2','内容\n\n# V2'));
});
test('同步网络返回期间的本地新输入不能丢失',()=>{
  const base={...fields,content:'a\nb\nc'};
  const sent={...base,content:'A\nb\nc'};
  const latest={...sent,content:'A\nb\nC'};
  const remote={...sent,title:'云端改名',id:'id',revision:2};
  const result=accepted({...latest,generation:3},{document:sent,generation:2},{status:'merged',document:remote});
  assert.equal(result.entry.content,'A\nb\nC');assert.equal(result.entry.title,'云端改名');assert.equal(result.entry.dirty,true);
  assert.equal(documentMerge(base,{...base,content:'电脑'},{...base,content:'手机'}),null);
});
