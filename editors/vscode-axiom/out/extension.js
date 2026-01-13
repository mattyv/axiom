"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
const path = __importStar(require("path"));
const vscode_1 = require("vscode");
const node_1 = require("vscode-languageclient/node");
let client;
let statusBarItem;
function updateStatusBar(state, message) {
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
function activate(context) {
    // Create status bar item
    statusBarItem = vscode_1.window.createStatusBarItem(vscode_1.StatusBarAlignment.Right, 100);
    statusBarItem.name = 'Axiom LSP Status';
    context.subscriptions.push(statusBarItem);
    updateStatusBar('starting');
    const config = vscode_1.workspace.getConfiguration('axiom-lsp');
    const mode = config.get('mode', 'default');
    // Try to find axiom-lsp in the workspace's .venv
    const workspaceFolder = vscode_1.workspace.workspaceFolders?.[0]?.uri.fsPath;
    let command = config.get('path', 'axiom-lsp');
    if (workspaceFolder && command === 'axiom-lsp') {
        const venvPath = path.join(workspaceFolder, '.venv', 'bin', 'axiom-lsp');
        command = venvPath;
    }
    const serverOptions = {
        command: command,
        args: ['--mode', mode],
    };
    const clientOptions = {
        documentSelector: [
            { scheme: 'file', language: 'c' },
            { scheme: 'file', language: 'cpp' },
        ],
        synchronize: {
            fileEvents: vscode_1.workspace.createFileSystemWatcher('**/*.{c,cpp,h,hpp,cc,cxx}'),
        },
    };
    client = new node_1.LanguageClient('axiom-lsp', 'Axiom LSP', serverOptions, clientOptions);
    // Track client state changes
    client.onDidChangeState((event) => {
        switch (event.newState) {
            case node_1.State.Starting:
                updateStatusBar('starting');
                break;
            case node_1.State.Running:
                updateStatusBar('running');
                break;
            case node_1.State.Stopped:
                updateStatusBar('stopped');
                break;
        }
    });
    client.start().catch((error) => {
        updateStatusBar('error', `Failed to start: ${error.message}`);
    });
}
function deactivate() {
    if (statusBarItem) {
        statusBarItem.dispose();
    }
    if (!client) {
        return undefined;
    }
    return client.stop();
}
//# sourceMappingURL=extension.js.map