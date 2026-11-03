import Cocoa
import WebKit

// Sem um menu Editar, o macOS nao entrega Cmd+C, Cmd+V e afins ao WKWebView.
@MainActor
private func dodaiosAddEditMenu() {
    let bar = NSApp.mainMenu ?? NSMenu()
    if bar.items.isEmpty {
        let appMenu = NSMenu()
        appMenu.addItem(
            withTitle: "Sair do DodaiOS",
            action: #selector(NSApplication.terminate(_:)),
            keyEquivalent: "q"
        )
        let appItem = NSMenuItem()
        appItem.submenu = appMenu
        bar.addItem(appItem)
    }
    if bar.items.contains(where: { $0.submenu?.title == "Editar" }) {
        return
    }
    let edit = NSMenu(title: "Editar")
    edit.addItem(withTitle: "Desfazer", action: Selector(("undo:")), keyEquivalent: "z")
    let redo = edit.addItem(withTitle: "Refazer", action: Selector(("redo:")), keyEquivalent: "z")
    redo.keyEquivalentModifierMask = [.command, .shift]
    edit.addItem(NSMenuItem.separator())
    edit.addItem(withTitle: "Recortar", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
    edit.addItem(withTitle: "Copiar", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
    edit.addItem(withTitle: "Colar", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
    edit.addItem(withTitle: "Selecionar tudo", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
    let item = NSMenuItem(title: "Editar", action: nil, keyEquivalent: "")
    item.submenu = edit
    bar.insertItem(item, at: min(1, bar.items.count))
    NSApp.mainMenu = bar
}

// Mantem o microfone e o painel vivos quando outra janela fica na frente.
private var dodaiosActivity: NSObjectProtocol?

private func dodaiosWebView(in view: NSView?) -> WKWebView? {
    guard let view else { return nil }
    if let web = view as? WKWebView { return web }
    for child in view.subviews {
        if let web = dodaiosWebView(in: child) { return web }
    }
    return nil
}

@MainActor
private func dodaiosKeepAliveInBackground() {
    dodaiosActivity = ProcessInfo.processInfo.beginActivity(
        options: [.userInitiated, .latencyCritical],
        reason: "Ensino por voz"
    )
    let setter = Selector(("_setPageVisibilityBasedProcessSuppressionEnabled:"))
    for window in NSApp.windows {
        if let preferences = dodaiosWebView(in: window.contentView)?.configuration.preferences,
           preferences.responds(to: setter) {
            preferences.perform(setter, with: nil)
        }
    }
}

func installDodaiosEditMenu() {
    NotificationCenter.default.addObserver(
        forName: NSApplication.didFinishLaunchingNotification,
        object: nil,
        queue: .main
    ) { _ in
        DispatchQueue.main.async {
            MainActor.assumeIsolated {
                dodaiosAddEditMenu()
                dodaiosKeepAliveInBackground()
            }
        }
    }
}
