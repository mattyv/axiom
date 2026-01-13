import * as path from 'path';
import { workspace, ExtensionContext, window, StatusBarAlignment, StatusBarItem } from 'vscode';
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
    State,
} from 'vscode-languageclient/node';

let client: LanguageClient;
let statusBarItem: StatusBarItem;

function updateStatusBar(state: 'starting' | 'running' | 'stopped' | 'error', message?: string) {
    if (!statusBarItem) {
        return;
    }

    switch (state) {
        case 'starting':
            statusBarItem.text = '$(sync~spin) Axiom: Initializing...';
            statusBarItem.tooltip = 'Axiom LSP is starting up and loading axiom database';
            statusBarItem.backgroundColor = undefined;
            statusBarItem.show();
            break;
        case 'running':
            statusBarItem.text = '$(check) Axiom: Ready';
            statusBarItem.tooltip = 'Axiom LSP is ready - hover over C++ code to see axioms';
            statusBarItem.backgroundColor = undefined;
            statusBarItem.show();
            break;
        case 'stopped':
            statusBarItem.text = '$(circle-slash) Axiom: Stopped';
            statusBarItem.tooltip = 'Axiom LSP is not running';
            statusBarItem.backgroundColor = undefined;
            statusBarItem.show();
            break;
        case 'error':
            statusBarItem.text = '$(error) Axiom: Error';
            statusBarItem.tooltip = message || 'Axiom LSP encountered an error';
            statusBarItem.backgroundColor = undefined;
            statusBarItem.show();
            break;
    }
}

export function activate(context: ExtensionContext) {
    // Create status bar item
    statusBarItem = window.createStatusBarItem(StatusBarAlignment.Right, 100);
    statusBarItem.name = 'Axiom LSP Status';
    context.subscriptions.push(statusBarItem);

    updateStatusBar('starting');

    const config = workspace.getConfiguration('axiom-lsp');
    const mode = config.get<string>('mode', 'default');

    // Try to find axiom-lsp in the workspace's .venv
    const workspaceFolder = workspace.workspaceFolders?.[0]?.uri.fsPath;
    let command = config.get<string>('path', 'axiom-lsp');

    if (workspaceFolder && command === 'axiom-lsp') {
        const venvPath = path.join(workspaceFolder, '.venv', 'bin', 'axiom-lsp');
        command = venvPath;
    }

    const serverOptions: ServerOptions = {
        command: command,
        args: ['--mode', mode],
    };

    const clientOptions: LanguageClientOptions = {
        documentSelector: [
            { scheme: 'file', language: 'c' },
            { scheme: 'file', language: 'cpp' },
        ],
        synchronize: {
            fileEvents: workspace.createFileSystemWatcher('**/*.{c,cpp,h,hpp,cc,cxx}'),
        },
    };

    client = new LanguageClient(
        'axiom-lsp',
        'Axiom LSP',
        serverOptions,
        clientOptions
    );

    // Track client state changes
    client.onDidChangeState((event) => {
        switch (event.newState) {
            case State.Starting:
                updateStatusBar('starting');
                break;
            case State.Running:
                updateStatusBar('running');
                break;
            case State.Stopped:
                updateStatusBar('stopped');
                break;
        }
    });

    client.start().catch((error) => {
        updateStatusBar('error', `Failed to start: ${error.message}`);
    });
}

export function deactivate(): Thenable<void> | undefined {
    if (statusBarItem) {
        statusBarItem.dispose();
    }
    if (!client) {
        return undefined;
    }
    return client.stop();
}
