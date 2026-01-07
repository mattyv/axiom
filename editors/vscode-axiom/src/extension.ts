import * as path from 'path';
import { workspace, ExtensionContext } from 'vscode';
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
} from 'vscode-languageclient/node';

let client: LanguageClient;

export function activate(_context: ExtensionContext) {
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

    client.start();
}

export function deactivate(): Thenable<void> | undefined {
    if (!client) {
        return undefined;
    }
    return client.stop();
}
