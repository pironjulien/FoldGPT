"""Create a reviewable installed-client inventory from the static AST evidence."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SELECTED_CATEGORIES = [
    'appHostService', 'hostFetchHandler', 'rpcTargetMethod', 'routeDefinition', 'dynamicRouteExpression',
    'settingDefinition', 'requestCall', 'protocolLiteral', 'methodProperty',
    'dispatchedMessage', 'postedTypedMessage', 'subscribedEvent', 'commandCall',
    'commandIdProperty', 'commandDefinitionCandidate', 'commandStringCandidate',
    'commandVectorCandidate', 'processProgram', 'moduleRequire', 'platformGuard',
    'explicitLimitation', 'versionRequirementCandidate', 'namedCallCandidate', 'namedMapEntryCandidate',
]


def load(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis', type=Path, required=True)
    parser.add_argument('--installed', type=Path, required=True)
    parser.add_argument('--comparison', type=Path, required=True)
    parser.add_argument('--external', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    for pathname in (args.analysis, args.installed, args.comparison):
        pathname.resolve(strict=True).relative_to(ROOT)
    if args.external:
        args.external.resolve(strict=True).relative_to(ROOT)
    args.output.resolve().relative_to(ROOT)
    if args.output.exists():
        raise ValueError('Output must be a new directory')
    report = load(args.analysis/'report.json')
    source_rows = load(args.analysis/'sources.json')
    source_map = {row['id']: row for row in source_rows}
    archives = load(args.comparison)
    package = load(args.installed/'asar/package.json')
    members = load(args.installed/'asar-inventory.json')
    external_rows = load(args.external/'inventory.json') if args.external else []
    external_by_path = {row['path']:row for row in external_rows}
    external_report = load(args.external/'report.json') if args.external else None
    surfaces, references, comparisons, category_counts = {}, {}, {}, {}

    def evidence(row):
        original = source_map[row['source']]
        key = ('external/' + original['path'].split('/installed-files/files/',1)[-1]
               if original['corpus']=='installedExternal' else original['path'].split('/asar/', 1)[-1])
        references[key] = {'path': key, 'sha256': original['sha256'], 'bytes': original['bytes'], 'parsed': original['parsed']}
        return {'file': key, 'offset': row['offset'], 'endOffset': row['endOffset'],
                'line': row['line'], 'column': row['column'], 'owner': row['owner']}

    def grouped(rows):
        groups = {}
        for row in rows:
            name = row['value']
            if name not in groups:
                details = {key: value for key,value in row.items()
                           if key not in ('source','value','offset','endOffset','line','column','owner')}
                groups[name] = {'name': name, 'occurrences': 0, 'firstEvidence': evidence(row), **details}
            groups[name]['occurrences'] += 1
        return [groups[key] for key in sorted(groups)]

    for category in SELECTED_CATEGORIES:
        filename = args.analysis/(category+'.json')
        rows = load(filename) if filename.exists() else []
        installed = [row for row in rows if row['source'].startswith(('installed:', 'installedExternal:'))]
        baseline_names = {row['value'] for row in rows if row['source'].startswith(('baseline:', 'baselineExternal:'))}
        installed_names = {row['value'] for row in installed}
        surfaces[category] = grouped(installed)
        category_counts[category] = {'occurrences':len(installed),'distinctValues':len(installed_names)}
        comparisons[category] = {'onlyInstalled':sorted(installed_names-baseline_names),
                                 'onlyBaseline':sorted(baseline_names-installed_names)}

    fetches = load(args.analysis/'hostFetchHandler.json')
    exact_fetches = [row for row in fetches if row['source'].startswith('installed:')
                     and row['source'].endswith('/.vite/build/main-C5K7o1Hr.js') and row['owner']=='iR']
    typed = load(args.analysis/'typedSwitchCase.json')
    messages = [row for row in typed if row['source'].startswith('installed:')
                and row['source'].endswith('/.vite/build/main-C5K7o1Hr.js') and row['owner']=='kxe.handleMessage']
    # The exact main file and enclosing classes were inspected and are version-bound.
    if len(exact_fetches) != 130 or len(messages) != 168:
        raise ValueError('Reviewed main-process handler location/count changed; re-inspect before summarizing')
    exact_surfaces = {'mainFetchHandlers': grouped(exact_fetches), 'mainIncomingMessageCases': grouped(messages)}
    callback_maps = load(args.analysis/'namedMapEntryCandidate.json')
    builtin_commands = [row for row in callback_maps if row['source'].startswith('installed:')
                        and row['source'].endswith('/webview/assets/app-initial-36a3a1b7313c.js') and row.get('mapExpression')=='xxi']
    if len(builtin_commands) != 25:
        raise ValueError('Reviewed built-in renderer command registry changed; re-inspect before summarizing')
    exact_surfaces['rendererBuiltinCommandMap'] = grouped(builtin_commands)
    rpc_methods = [row for row in load(args.analysis/'rpcTargetMethod.json') if row['source'].startswith(('installed:', 'installedExternal:'))]
    exact_surfaces['rpcTargetMethodsByClass'] = [
        {'className':row['className'], 'method':row['value'], 'parameters':row['parameters'],
         'kind':row['kind'], 'evidence':evidence(row)} for row in rpc_methods]
    bindings = [row for row in load(args.analysis/'classInstanceBinding.json') if row['source'].startswith('installed:')]
    service_rows = [row for row in load(args.analysis/'appHostService.json') if row['source'].startswith('installed:')]
    exact_surfaces['appHostServiceBindings'] = []
    for service in service_rows:
        candidates = [row for row in bindings if row['source']==service['source'] and row['value']==service['implementation']]
        exact_surfaces['appHostServiceBindings'].append({
            'service':service['value'], 'implementationExpression':service['implementation'],
            'evidence':evidence(service),
            'sameExpressionClassAssignments':[{'classExpression':row['implementation'],'evidence':evidence(row)} for row in candidates],
            'scope':'Static expression matches; constructor injection and dynamic dispatch are not resolved'})
    native_members = [row for row in members if Path(row['path']).suffix in ('.node','.wasm')]
    uncollected, external_member_checks = [], []
    for row in members:
        if row.get('link'):
            uncollected.append(row)
        elif row.get('unpacked'):
            external_name = 'resources/app.asar.unpacked/' + row['path']
            collected = external_by_path.get(external_name)
            if collected is None:
                uncollected.append(row)
                continue
            check = {'archivePath':row['path'],'externalPath':external_name,'declaredBytes':row['bytes'],
                     'collectedBytes':collected['bytes'],'collectedSha256':collected.get('sha256'),
                     'sizeMatches':row['bytes']==collected['bytes']}
            if not check['sizeMatches']:
                raise ValueError('Unpacked member size differs: '+external_name)
            external_member_checks.append(check)
    result = {
        'schema':'foldgpt.installed-desktop-review.v1',
        'generatedAt':report['generatedAt'],
        'installedPackage':{'name':package['name'],'version':package['version'],'entryPoint':package['main'],
                            'archive':archives['installed']},
        'baselinePackage':archives['baseline'],
        'installedExternalCollection':external_report,
        'coverage':report['coverage'],
        'parser':report['parser'],
        'offsetUnit':report['offsetUnit'],
        'allInspectedSourceBytesUnchanged':report['allInspectedSourceBytesUnchanged'],
        'parseErrorCount':report['parseErrorCount'],
        'rawAnalysis':{'path':str(args.analysis.resolve().relative_to(ROOT)).replace('\\','/'),
                       'reportSha256':sha(args.analysis/'report.json'),'sourcesSha256':sha(args.analysis/'sources.json')},
        'scope':'Static review of all available packed and externally collected JavaScript; no execution of official client code, no native disassembly, no claim that every named operation is available or works on Android.',
        'categoryCounts':category_counts,
        'reviewedMainSurfaces':exact_surfaces,
        'surfaces':surfaces,
        'declaredDependencies':package.get('dependencies',{}),
        'declaredOptionalDependencies':package.get('optionalDependencies',{}),
        'nativeAndWasmMembers':native_members,
        'unpackedOrLinkedNotCollected':uncollected,
        'unpackedMemberCollectionChecks':external_member_checks,
        'dynamicOccurrencesAcrossAllCorpora':report['unresolvedDynamicOccurrences'],
        'installedVsBaselineNamedSurfaces':comparisons,
        'archivePathComparison':{'added':len(archives['added']),'removed':len(archives['removed']),
                                 'changedSamePath':archives['changedSamePath'],
                                 'unchangedPacked':len(archives['unchangedPacked']),
                                 'unpackedOrLinkedNotByteCompared':len(archives['unpackedOrLinkedNotByteCompared'])},
        'liveAssetChecks':archives['liveAssetChecks'],
        'sourceReferences':references,
        'toolSources':{str(file.relative_to(ROOT)).replace('\\','/'):sha(file) for file in (
            ROOT/'tools/desktop-audit/extract-asar.py', ROOT/'tools/desktop-audit/inventory-surfaces.mjs',
            ROOT/'tools/desktop-audit/test-inventory.mjs', ROOT/'tools/desktop-audit/summarize-surfaces.py')},
    }
    args.output.mkdir(parents=True, exist_ok=False)
    destination = args.output/'installed-client-inventory.json'
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (args.output/'analysis-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(destination),'bytes':destination.stat().st_size,
                      'sha256':sha(destination),'categories':category_counts,
                      'mainFetchHandlers':len(exact_surfaces['mainFetchHandlers']),
                      'mainIncomingMessageCases':len(exact_surfaces['mainIncomingMessageCases'])}))


if __name__ == '__main__':
    main()
