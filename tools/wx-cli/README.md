# wx-cli runtime

This directory keeps `@jackwener/wx-cli` isolated from the global Node.js
installation.

Install the pinned dependency:

```powershell
npm.cmd install --prefix tools/wx-cli
```

Run it from the repository root:

```powershell
npm.cmd --prefix tools/wx-cli run wx -- --help
```

On Windows, integrations can invoke the local shim directly at
`tools/wx-cli/node_modules/.bin/wx.cmd`.
