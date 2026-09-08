import assert from 'node:assert/strict';
import test from 'node:test';
import {analyzeSource} from './inventory-surfaces.mjs';

test('records actual host handlers and schemas without interpreting string contents as code', () => {
  const result = analyzeSource('class X { handlers={"get-setting":async({key})=>({value:key})}; } const text="handlers={fake(){}}";');
  const handlers = result.observations.filter(row => row.category === 'hostFetchHandler');
  assert.equal(handlers.length, 1);
  assert.equal(handlers[0].value, 'get-setting');
  assert.deepEqual(handlers[0].parameters, ['{key}']);
  assert.equal(handlers[0].asynchronous, true);
});

test('keeps literal methods distinct from unresolved dynamic methods', () => {
  const result = analyzeSource('client.sendRequest("thread/resume", {}); client.sendRequest(method, {});');
  assert.deepEqual(result.observations.filter(row => row.category === 'requestCall').map(row => row.value), ['thread/resume']);
  assert.equal(result.dynamic.requestCall, 1);
});

test('does not execute input and reports the exact UTF-16 position of an observation', () => {
  globalThis.foldgptAuditExecuted = false;
  const source = 'globalThis.foldgptAuditExecuted=true;\nclient.dispatchMessage("hello-world",{});';
  const result = analyzeSource(source);
  assert.equal(globalThis.foldgptAuditExecuted, false);
  const message = result.observations.find(row => row.category === 'dispatchedMessage');
  assert.equal(message.line, 2);
  assert.equal(message.column, 0);
  assert.equal(source.slice(message.offset, message.endOffset), 'client.dispatchMessage("hello-world",{})');
  delete globalThis.foldgptAuditExecuted;
});

test('keeps filesystem path candidates separate from configured routes', () => {
  const result = analyzeSource('const file={path:"/tmp/project"}; const route={path:"/settings",element:component};');
  assert.deepEqual(result.observations.filter(row => row.category === 'routeDefinition').map(row => row.value), ['/settings']);
  assert.deepEqual(result.observations.filter(row => row.category === 'pathPropertyCandidate').map(row => row.value), ['/tmp/project']);
});

test('finds registered app-host services and public RpcTarget methods', () => {
  const result = analyzeSource('class Service extends n.uu { async editLocal({projectId}) {} #internal(){} } class Host { createAppHost(){return new Target({settings:this.settings,projects:new Service})} }');
  assert.deepEqual(result.observations.filter(row => row.category === 'rpcTargetMethod').map(row => row.value), ['editLocal']);
  assert.deepEqual(result.observations.filter(row => row.category === 'appHostService').map(row => row.value), ['settings', 'projects']);
});

test('refuses malformed syntax rather than reporting partial coverage as successful', () => {
  assert.throws(() => analyzeSource('const x = ;'), SyntaxError);
});

test('finds programs in process option objects while retaining unresolved vector heads', () => {
  const result = analyzeSource('host.spawn({args:["git","status"]}); host.spawn({args:[binary,"status"]});');
  assert.deepEqual(result.observations.filter(row => row.category === 'processProgram').map(row => row.value), ['git']);
  assert.equal(result.dynamic.processProgram, 1);
  assert.equal(result.dynamic.commandVectorCandidate, 1);
});

test('retains unresolved route expressions and named callback maps without executing callbacks', () => {
  const result = analyzeSource('const route={path:definition.route,lazy:()=>{}}; const commands=new Map([["newTask",handler],["label","data"]]);');
  assert.equal(result.dynamic.routeDefinition, 1);
  assert.equal(result.observations.find(row => row.category === 'dynamicRouteExpression').value, 'definition.route');
  const entries = result.observations.filter(row => row.category === 'namedMapEntryCandidate');
  assert.equal(entries.length, 1);
  assert.equal(entries[0].value, 'newTask');
  assert.equal(entries[0].mapExpression, 'commands');
});
