// Static syntax inventory. Never import or execute the inspected client modules.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const require = createRequire(import.meta.url);
export const parser = require(path.join(project, 'work/desktop-audit-parser/node_modules/acorn'));
const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const posix = value => value.replaceAll('\\', '/');
const staticString = node => node?.type === 'Literal' && typeof node.value === 'string' ? node.value
  : node?.type === 'TemplateLiteral' && node.expressions.length === 0 ? node.quasis[0].value.cooked : null;
const keyName = node => node?.type === 'Identifier' ? node.name : staticString(node);
const memberName = node => node?.type === 'MemberExpression' ? keyName(node.property) : keyName(node);
const property = (node, name) => node?.type === 'ObjectExpression'
  ? node.properties.find(p => p.type === 'Property' && keyName(p.key) === name) : undefined;
const methodPattern = /^[A-Za-z][A-Za-z0-9]*(?:\/[A-Za-z][A-Za-z0-9]*)+$/;
const commandPattern = /^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$/;

export function analyzeSource(source, filename = 'fixture.js') {
  const observations = [];
  const dynamic = {};
  const lineStarts = [0];
  for (let i = 0; i < source.length; i++) if (source.charCodeAt(i) === 10) lineStarts.push(i + 1);
  const snippet = node => node ? source.slice(node.start, Math.min(node.end, node.start + 240)) : null;
  function position(offset) {
    let low = 0, high = lineStarts.length;
    while (low + 1 < high) { const middle = (low + high) >>> 1; if (lineStarts[middle] <= offset) low = middle; else high = middle; }
    return {line: low + 1, column: offset - lineStarts[low]};
  }
  function add(category, value, node, context, details = {}) {
    if (typeof value !== 'string') { dynamic[category] = (dynamic[category] ?? 0) + 1; return; }
    observations.push({category, value, offset: node.start, endOffset: node.end,
      ...position(node.start), owner: context.owner, ...details});
  }
  let syntax;
  let sourceType = filename.endsWith('.cjs') ? 'script' : 'module';
  try { syntax = parser.parse(source, {ecmaVersion: 'latest', sourceType, allowHashBang: true}); }
  catch (moduleError) {
    if (sourceType === 'script') throw moduleError;
    sourceType = 'script';
    try { syntax = parser.parse(source, {ecmaVersion: 'latest', sourceType, allowHashBang: true, allowReturnOutsideFunction: true}); }
    catch { throw moduleError; }
  }
  const stack = [{node: syntax, parent: null, context: {owner: '<module>', rpcClass: false}}];
  while (stack.length) {
    let {node, parent, context} = stack.pop();
    if (!node || typeof node.type !== 'string') continue;
    if (node.type === 'ClassExpression' || node.type === 'ClassDeclaration') {
      const className = node.id?.name ?? (parent?.type === 'VariableDeclarator' ? keyName(parent.id) : '<anonymous-class>');
      const base = snippet(node.superClass);
      // Main-process service targets inherit the imported RpcTarget (n.uu in this build).
      context = {owner: className, className, rpcClass: base === 'n.uu'};
      if (context.rpcClass) add('rpcTargetClass', className, node, context, {base});
    } else if (node.type === 'MethodDefinition') {
      const method = keyName(node.key);
      if (context.rpcClass && !node.static && node.key?.type !== 'PrivateIdentifier')
        add('rpcTargetMethod', method, node, context, {className: context.className,
          parameters: node.value.params.map(snippet), kind: node.kind});
      context = {...context, owner: context.className ? context.className + '.' + (method ?? '<dynamic>') : method, method};
    } else if (node.type === 'FunctionDeclaration' && node.id) {
      context = {...context, owner: node.id.name};
    }

    if (node.type === 'ImportDeclaration' || node.type === 'ExportAllDeclaration'
        || node.type === 'ExportNamedDeclaration' && node.source) {
      add('moduleImport', staticString(node.source), node, context, {kind: node.type,
        bindings: node.specifiers?.map(s => ({local: s.local?.name, imported: keyName(s.imported), exported: keyName(s.exported)}))});
    }
    if (node.type === 'ExportNamedDeclaration' && !node.source)
      for (const s of node.specifiers) add('moduleExport', keyName(s.exported), s, context, {local: keyName(s.local)});
    if (node.type === 'ImportExpression') add('dynamicModuleImport', staticString(node.source), node, context);
    if ((node.type === 'PropertyDefinition' || node.type === 'Property') && keyName(node.key) === 'handlers'
        && node.value?.type === 'ObjectExpression') {
      for (const handler of node.value.properties) {
        if (handler.type !== 'Property') { dynamic.hostFetchHandler = (dynamic.hostFetchHandler ?? 0) + 1; continue; }
        add('hostFetchHandler', keyName(handler.key), handler, context,
          {parameters: handler.value?.params?.map(snippet) ?? null, asynchronous: handler.value?.async ?? null});
      }
    }
    if (node.type === 'SwitchCase' && parent?.type === 'SwitchStatement'
        && parent.discriminant?.type === 'MemberExpression' && memberName(parent.discriminant) === 'type')
      add('typedSwitchCase', staticString(node.test), node.test ?? node, context,
        {discriminant: snippet(parent.discriminant), interpretation: 'Typed branch; not necessarily a host message'});

    if (node.type === 'Property' && parent?.type === 'ObjectExpression') {
      const name = keyName(node.key), value = staticString(node.value);
      if (name === 'method') add('methodProperty', value, node, context);
      if (name === 'commandId') add('commandIdProperty', value, node, context);
      if (['args', 'argv', 'command'].includes(name) && node.value.type === 'ArrayExpression')
        add('commandVectorCandidate', staticString(node.value.elements[0]), node, context,
          {key: name, expression: snippet(node.value), interpretation: 'Static vector head; may be data or an invocation'});
      if (name === 'command' && value != null)
        add('commandStringCandidate', value, node, context, {interpretation: 'Command field; execution was not observed'});
      if (name === 'id' && value != null && ['handler', 'execute', 'accelerator', 'keybindings', 'keybinding'].some(key => property(parent, key)))
        add('commandDefinitionCandidate', value, node, context, {objectKeys: parent.properties.map(p => keyName(p.key)).filter(Boolean)});
      if (name === 'path') {
        const routeKeys = parent.properties.filter(p => p.type === 'Property').map(p => keyName(p.key));
        const isRoute = routeKeys.some(key => ['element', 'Component', 'lazy', 'errorElement', 'caseSensitive', 'loader'].includes(key));
        if (value != null || isRoute) add(isRoute ? 'routeDefinition' : 'pathPropertyCandidate', value, node, context, {objectKeys: routeKeys});
        if (isRoute && value == null) add('dynamicRouteExpression', snippet(node.value), node, context,
          {objectKeys: routeKeys, interpretation: 'Route expression exists; actual path not resolved by static extraction'});
      }
      if (name === 'key' && value != null && property(parent, 'schema') && property(parent, 'description'))
        add('settingDefinition', value, node, context, {agentAccess: staticString(property(parent, 'agentAccess')?.value),
          description: staticString(property(parent, 'description')?.value), defaultExpression: snippet(property(parent, 'default')?.value),
          schemaExpression: snippet(property(parent, 'schema')?.value)});
      if (value != null && /^[\w.-]+\/(?:updated|started|completed|read|list|write|update|resume|start|stop|spawn|changed)$/.test(value))
        add('protocolStringCandidate', value, node, context, {key: name});
      if (value != null && /^0\.\d+\.\d+(?:-alpha\.\d+)?$/.test(value))
        add('versionRequirementCandidate', value, node, context, {key: name});
    }
    if (node.type === 'NewExpression' && context.method === 'createAppHost') {
      const services = node.arguments.find(a => a.type === 'ObjectExpression');
      if (services && services.properties.some(p => keyName(p.key) === 'settings')
          && services.properties.some(p => keyName(p.key) === 'projects'))
        for (const service of services.properties) {
          if (service.type === 'Property') add('appHostService', keyName(service.key), service, context, {implementation: snippet(service.value)});
          else dynamic.appHostService = (dynamic.appHostService ?? 0) + 1;
        }
    }
    if (node.type === 'NewExpression' && keyName(node.callee) === 'Map' && node.arguments[0]?.type === 'ArrayExpression')
      for (const pair of node.arguments[0].elements) {
        if (pair?.type !== 'ArrayExpression' || pair.elements.length !== 2) continue;
        const [key, value] = pair.elements;
        if (!['Identifier', 'MemberExpression', 'ArrowFunctionExpression', 'FunctionExpression'].includes(value?.type)) continue;
        add('namedMapEntryCandidate', staticString(key), pair, context,
          {mapExpression: snippet(parent?.type === 'AssignmentExpression' ? parent.left : parent?.type === 'VariableDeclarator' ? parent.id : null),
            valueExpression: snippet(value), interpretation: 'Named callback or reference map; not automatically a command registry'});
      }
    if (node.type === 'AssignmentExpression' && node.left.type === 'MemberExpression'
        && node.right.type === 'NewExpression')
      add('classInstanceBinding', snippet(node.left), node, context, {implementation: snippet(node.right.callee)});

    if (node.type === 'CallExpression' || node.type === 'NewExpression') {
      const name = memberName(node.callee), first = staticString(node.arguments[0]);
      if (node.callee.type === 'Identifier' && node.callee.name === 'require')
        add('moduleRequire', first, node, context);
      if (['sendRequest', 'sendInternalRequest', 'request', 'requestNotification', 'sendNotification'].includes(name)) {
        const parameter = node.arguments[0];
        add('requestCall', first ?? staticString(property(parameter, 'method')?.value), node, context,
          {callee: snippet(node.callee), methodIsExplicit: first != null || property(parameter, 'method') != null});
      }
      if (name === 'dispatchMessage' || name === 'subscribe')
        add(name === 'dispatchMessage' ? 'dispatchedMessage' : 'subscribedEvent', first, node, context, {callee: snippet(node.callee)});
      if (['registerCommand', 'executeCommand', 'dispatchCommand'].includes(name))
        add('commandCall', first, node, context, {callee: snippet(node.callee)});
      if (name && /^(?:sendMessage|postMessage)/.test(name))
        for (const argument of node.arguments) {
          const type = property(argument, 'type');
          if (type) add('postedTypedMessage', staticString(type.value), argument, context, {callee: snippet(node.callee)});
        }
      if (first != null && commandPattern.test(first))
        add('namedCallCandidate', first, node, context, {callee: snippet(node.callee), interpretation: 'Static named call; may be UI label or library argument'});
      if (first != null && methodPattern.test(first))
        add('slashCallCandidate', first, node, context, {callee: snippet(node.callee)});
      if (['spawn', 'spawnSync', 'execFile', 'execFileSync', 'fork'].includes(name)) {
        const options = node.arguments[0], vector = property(options, 'args')?.value ?? property(options, 'command')?.value;
        add('processProgram', first ?? (vector?.type === 'ArrayExpression' ? staticString(vector.elements[0]) : null), node, context,
          {callee: snippet(node.callee), argumentsExpression: snippet(first ? node.arguments[1] : vector)});
      }
      if (['Error', 'TypeError'].includes(name) && first != null && /unsupported|not supported|not implemented|unavailable/i.test(first))
        add('explicitLimitation', first, node, context, {interpretation: 'Observed code branch, not proof this branch is reached'});
    }
    if (node.type === 'BinaryExpression' && ['===', '!==', '==', '!='].includes(node.operator)) {
      for (const [member, literal] of [[node.left, node.right], [node.right, node.left]]) {
        const value = staticString(literal);
        if (member?.type === 'MemberExpression' && ['platform', 'arch'].includes(memberName(member)) && value != null)
          add('platformGuard', value, node, context, {expression: snippet(node)});
      }
    }
    // Broad protocol literals retain coverage when minification hides call names.
    if (node.type === 'Literal' || node.type === 'TemplateLiteral') {
      const value = staticString(node);
      if (value && /^(thread|turn|item|process|fs|config|project|account|plugin|skills|mcpServer|model|environment|command)\/[A-Za-z]/.test(value)
          && methodPattern.test(value)) add('protocolLiteral', value, node, context);
      if (value && /^(node:|vscode:\/\/codex\/|codex:|app:\/\/)/.test(value))
        add('hostAddressLiteral', value, node, context);
    }
    for (const [key, value] of Object.entries(node)) {
      if (['start', 'end', 'loc', 'raw'].includes(key)) continue;
      if (Array.isArray(value)) {
        for (let i = value.length - 1; i >= 0; i--) if (value[i]?.type) stack.push({node: value[i], parent: node, context});
      } else if (value?.type) stack.push({node: value, parent: node, context});
    }
  }
  return {sourceType, observations, dynamic};
}

function contained(value) {
  const absolute = fs.realpathSync(value), relative = path.relative(project, absolute);
  if (relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative)) throw Error('Input must be under project');
  return absolute;
}
function allFiles(root) {
  if (fs.statSync(root).isFile()) return [root];
  const files = [], pending = [root];
  while (pending.length) for (const entry of fs.readdirSync(pending.pop(), {withFileTypes: true})) {
    const pathname = path.join(entry.parentPath, entry.name);
    if (entry.isDirectory()) pending.push(pathname);
    else if (entry.isFile()) files.push(pathname);
    else throw Error('Uninspected filesystem alias: ' + pathname);
  }
  return files.sort();
}

async function main() {
  const args = process.argv.slice(2), corpora = []; let output;
  for (let i = 0; i < args.length; i += 2) {
    if (args[i] === '--output') output = path.resolve(args[i + 1]);
    else if (args[i] === '--corpus') {
      const split = args[i + 1].indexOf('=');
      if (split < 1) throw Error('Corpus must be name=path');
      corpora.push({name: args[i + 1].slice(0, split), root: contained(args[i + 1].slice(split + 1))});
    } else throw Error('Unknown argument: ' + args[i]);
  }
  if (!output || corpora.length === 0) throw Error('Provide --corpus name=path and --output directory');
  contained(path.dirname(output));
  if (fs.existsSync(output)) throw Error('Output must be a new directory');
  fs.mkdirSync(output);
  const sources = [], entries = new Map(), categoryCounts = {}, unresolved = {}, coverage = [];
  let processed = 0;
  for (const corpus of corpora) {
    const files = allFiles(corpus.root), row = {name: corpus.name, root: posix(path.relative(project, corpus.root)),
      filesAvailable: files.length, javascriptFiles: 0, parsed: 0, parseErrors: 0, sourceMapsAvailable: 0};
    for (const file of files) {
      if (file.endsWith('.map')) { row.sourceMapsAvailable++; continue; }
      if (!/\.(?:js|cjs|mjs)$/.test(file)) continue;
      row.javascriptFiles++;
      const bytes = fs.readFileSync(file), fileId = corpus.name + ':' + posix(path.relative(project, file));
      const record = {id: fileId, corpus: corpus.name, path: posix(path.relative(project, file)), bytes: bytes.length, sha256: digest(bytes)};
      try {
        const result = analyzeSource(bytes.toString('utf8'), file);
        record.parsed = true; record.sourceType = result.sourceType; record.observations = result.observations.length;
        row.parsed++;
        for (const observation of result.observations) {
          const category = observation.category; delete observation.category;
          const list = entries.get(category) ?? []; list.push({source: fileId, ...observation}); entries.set(category, list);
          categoryCounts[category] = (categoryCounts[category] ?? 0) + 1;
        }
        for (const [category, count] of Object.entries(result.dynamic)) unresolved[category] = (unresolved[category] ?? 0) + count;
      } catch (error) {
        record.parsed = false; record.parseError = String(error.message); row.parseErrors++;
      }
      if (digest(fs.readFileSync(file)) !== record.sha256) throw Error('Source changed during inventory: ' + file);
      sources.push(record);
      processed++;
      if (processed % 500 === 0) process.stdout.write(JSON.stringify({processed, corpus: corpus.name, parseErrors: row.parseErrors}) + '\n');
    }
    coverage.push(row);
  }
  const categories = [];
  for (const [category, values] of [...entries].sort(([a], [b]) => a.localeCompare(b))) {
    const filename = category + '.json';
    fs.writeFileSync(path.join(output, filename), JSON.stringify(values) + '\n', {flag: 'wx'});
    categories.push({category, observations: values.length, distinctValues: new Set(values.map(v => v.value)).size,
      file: filename, sha256: digest(fs.readFileSync(path.join(output, filename)))});
  }
  fs.writeFileSync(path.join(output, 'sources.json'), JSON.stringify(sources, null, 2) + '\n', {flag: 'wx'});
  const report = {schema: 'foldgpt.desktop-static-surface.v1', generatedAt: new Date().toISOString(),
    parser: {name: 'acorn', version: parser.version, ecmaVersion: 'latest', execution: 'Parsing only; client code was not executed'},
    offsetUnit: 'UTF-16 code units, zero-based; lines one-based; columns zero-based',
    coverage, categories, unresolvedDynamicOccurrences: unresolved,
    parseErrorCount: sources.filter(s => !s.parsed).length, allInspectedSourceBytesUnchanged: true,
    scope: 'All JavaScript files available under explicit corpus roots parsed or recorded as parse failures. Candidate categories are not verified commands. No claim of complete source recovery, native-code decompilation, dynamically generated names or runtime feature support.'};
  fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n', {flag: 'wx'});
  process.stdout.write(JSON.stringify({output, coverage, categoryCounts, parseErrors: report.parseErrorCount}) + '\n');
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
