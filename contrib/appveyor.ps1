# -*- coding: utf-8 -*-
#
# Copyright (C) 2016 Edgewall Software
# Copyright (C) 2016 Christian Boos <cboos@edgewall.org>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://trac.edgewall.com/license.html.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://trac.edgewall.org/.

# ------------------------------------------------------------------
#  This is a PowerShell script implementing the build steps used by
#  the AppVeyor Continuous Delivery service for Windows, Trac project.
#
#  The builds results are published at:
#
#    https://ci.appveyor.com/project/edgewall/trac
#
#  or, for Git topic branches pushed on GitHub forks, at:
#
#    https://ci.appveyor.com/project/<developer-user-id>/trac
#
# ------------------------------------------------------------------

# ------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------

# Update the following variables to match the current build
# environment on AppVeyor.
#
# See in particular:
#  - http://www.appveyor.com/docs/installed-software#python
#  - http://www.appveyor.com/docs/installed-software#mingw-msys-cygwin
#  - http://www.appveyor.com/docs/services-databases#mysql
#  - http://www.appveyor.com/docs/services-databases#postgresql

$msysHome = 'C:\msys64\usr\bin'
$deps     = 'C:\projects\dependencies'

$mysqlHome = 'C:\Program Files\MySql\MySQL Server 5.7'
$mysqlPwd  = 'Password12!'

$pgHome     = 'C:\Program Files\PostgreSQL\9.3'
$pgUser     = 'postgres'
$pgPassword = 'Password12!'


# External Python dependencies

$pipCommonPackages = @(
    'genshi',
    'babel!=2.3.0,!=2.3.1',
    'twill==0.9.1',
    'configobj',
    'docutils',
    'pygments',
    'pytz',
    'textile',
    'wheel'
)

$fcrypt    = "$deps\fcrypt-1.3.1.tar.gz"
$fcryptUrl = 'http://www.carey.geek.nz/code/python-fcrypt/fcrypt-1.3.1.tar.gz'

$svnBase = "svn-win32-1.8.15"
$svnBaseAp = "$svnBase-ap24"
$svnUrlBase = "https://sourceforge.net/projects/win32svn/files/1.8.15/apache24"

$pipPackages = @{
    '1.0-stable' = @($fcrypt)
    trunk = @('passlib')
}

$condaCommonPackages = @(
    'lxml'
)

# ------------------------------------------------------------------
# "Environment" environment variables
# ------------------------------------------------------------------

# In the build matrix, we can set arbitrary environment variables
# which together define the software configuration that will be
# tested.

# These variables are:
#  - SVN_BRANCH: the line of development (1.0-stable, ... trunk)
#  - PYTHONHOME: the version of python we are testing
#  - TRAC_TEST_DB_URI: the database backend we are testing
#  - SKIP_ENV: don't perform any step with this environment (optional)
#  - SKIP_BUILD: don't execute the Build step for this environment (optional)
#  - SKIP_TESTS: don't execute the Tests step for this environment (optional)
#
# Note that any combination should work, except for MySQL which can
# only be installed conveniently from a Conda version of Python.

# "Aliases"

$pyHome = $env:PYTHONHOME
$usingMysql      = $env:TRAC_TEST_DB_URI -match '^mysql:'
$usingPostgresql = $env:TRAC_TEST_DB_URI -match '^postgres:'
$skipInstall = [bool]$env:SKIP_ENV
$skipBuild   = $env:SKIP_BUILD -or $env:SKIP_ENV
$skipTests   = $env:SKIP_TESTS -or $env:SKIP_ENV

$svnBranch = $env:SVN_BRANCH


# ------------------------------------------------------------------
# Utilities
# ------------------------------------------------------------------

# Documentation for AppVeyor API (Add-AppveyorMessage, etc.) can be
# found at: http://www.appveyor.com/docs/build-worker-api

function Write-Step([string]$name, [bool]$skip) {
    if ($skip) {
        $message = "Skipping step $name"
        Write-Host $message
        Add-AppveyorMessage -Message $message
    }
    else {
        Write-Host @"

------------------------------------------------------------------
$name
------------------------------------------------------------------
"@
    }
}

# Make it easier to run the tests locally, for debugging.
#
# Note that for this you may need to enable sourcing local scripts,
# from your PowerShell console:
#
#   Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process
#
#   . .\contrib\appveyor.ps1
#
# See http://trac.edgewall.org/wiki/AppVeyor for additional info.

if (-not $env:APPVEYOR) {
    function Debug-Caller {
	$caller = (Get-Variable MyInvocation -Scope 1).Value.MyCommand.Name
	Write-Debug "$caller $args"
    }
    function Add-AppveyorMessage() { Debug-Caller @args }
    function Add-AppveyorTest() { Debug-Caller @args }
    function Update-AppveyorTest() { Debug-Caller @args }
    function Push-AppveyorArtifact() { Debug-Caller @args }
}


# ------------------------------------------------------------------
# Prologue
# ------------------------------------------------------------------

# Actions common to all steps (set up the PATH, determine Python version...)

$env:Path = "$pyHome;$pyHome\Scripts;$msysHome;$($env:Path)"

$pyV = [string](& python.exe -c 'import sys; print sys.version' 2>&1)
$pyVersion = if ($pyV -match '^(\d\.\d)') { $Matches[1] }
$py64 = ($pyV -match '64 bit')
$pyIsConda = $pyV -match 'Continuum Analytics'

# Subversion support
if (-not $py64) {
    $env:Path = "$deps\$svnBase\bin;$($env:Path)"
    $env:PYTHONPATH = "$deps\$pyVersion\$svnBase\python;$($env:PYTHONPATH)"
}



# ------------------------------------------------------------------
# Steps
# ------------------------------------------------------------------

function Trac-Install {

    Write-Step -Name INSTALL -Skip $skipInstall

    if ($skipInstall) {
        return
    }

    if (-not (Test-Path $deps)) {
        & mkdir $deps
    }

    # Download fcrypt if needed (only for 1.0-stable after #12239)

    if ($svnBranch -eq '1.0-stable') {
        if (-not (Test-Path $fcrypt)) {
            & curl.exe -sS $fcryptUrl -o $fcrypt
        }
    }

    # Subversion support via win32svn project, for Python 2.6 and 2.7 32-bits

    if (-not $py64) {
        $svnBinariesZip = "$deps\$svnBaseAp.zip"
        if (-not (Test-Path $svnBinariesZip)) {
            & curl.exe -Ss -L -o $svnBinariesZip `
                "$svnUrlBase/$svnBaseAp.zip/download"
            & unzip.exe $svnBinariesZip -d $deps
        }

        $svnPython = "$($svnBaseAp)_py$($pyVersion -replace '\.', '')"
        $svnPythonZip = "$deps\$svnPython.zip"
        if (-not (Test-Path $svnPythonZip)) {
            & curl.exe -Ss -L -o $svnPythonZip `
                "$svnUrlBase/$svnPython.zip/download"
            & mkdir "$deps\$pyVersion"
            & unzip $svnPythonZip -d "$deps\$pyVersion"
        }
    }

    # Install packages via pip

    # pip in Python 2.6 triggers the following warning:
    # https://urllib3.readthedocs.org/en/latest/security.html#insecureplatformwarning
    # use -W to avoid it
    if ($pyVersion -eq '2.6') {
        $ignoreWarnings = @(
            '-W', 'ignore:A true SSLContext object is not available'
        )
    }

    function pip() {
        & python.exe $ignoreWarnings -m pip.__main__ @args
        # Note: -m pip works only in 2.7, -m pip.__main__ works in both
    }

    & pip --version

    if ($pyVersion -eq '2.6') {
        $pipPy26Deps = @(
            'https://files.pythonhosted.org/packages/67/4b/141a581104b1f6397bfa78ac9d43d8ad29a7ca43ea90a2d863fe3056e86a/six-1.11.0-py2.py3-none-any.whl'
            'https://files.pythonhosted.org/packages/c5/db/e56e6b4bbac7c4a06de1c50de6fe1ef3810018ae11732a50f15f62c7d050/enum34-1.1.6-py2-none-any.whl'
            'https://files.pythonhosted.org/packages/fc/d0/7fc3a811e011d4b388be48a0e381db8d990042df54aa4ef4599a31d39853/ipaddress-1.0.22-py2.py3-none-any.whl'
            'https://files.pythonhosted.org/packages/8c/2d/aad7f16146f4197a11f8e91fb81df177adcc2073d36a17b1491fd09df6ed/pycparser-2.18.tar.gz'
            'https://files.pythonhosted.org/packages/ea/cd/35485615f45f30a510576f1a56d1e0a7ad7bd8ab5ed7cdc600ef7cd06222/asn1crypto-0.24.0-py2.py3-none-any.whl'
            'https://files.pythonhosted.org/packages/27/cc/6dd9a3869f15c2edfab863b992838277279ce92663d334df9ecf5106f5c6/idna-2.6-py2.py3-none-any.whl'
            'https://files.pythonhosted.org/packages/7c/e6/92ad559b7192d846975fc916b65f667c7b8c3a32bea7372340bfe9a15fa5/certifi-2018.4.16-py2.py3-none-any.whl'
            'https://files.pythonhosted.org/packages/79/db/7c0cfe4aa8341a5fab4638952520d8db6ab85ff84505e12c00ea311c3516/pyOpenSSL-17.5.0-py2.py3-none-any.whl'
            'https://files.pythonhosted.org/packages/3f/08/7347ca4021e7fe0f1ab8f93cbc7d2a7a7350012300ad0e0227d55625e2b8/pip-1.5.6-py2.py3-none-any.whl'
        )
        if ($py64) {
            $pipPy26Deps += @(
                'https://files.pythonhosted.org/packages/c6/3a/e2698ef21b88e2dc3af4897e522abbeb7db861d342995ac7d35f9cef254b/cffi-1.10.0-cp26-cp26m-win_amd64.whl'
                'https://files.pythonhosted.org/packages/64/73/64eb5d9db4d293f3ddc18eee1af2f5a80818cee6a0e8039e11888caafa51/cryptography-2.0.3-cp26-cp26m-win_amd64.whl'
            )
        }
        else {
            $pipPy26Deps += @(
                'https://files.pythonhosted.org/packages/7e/b6/8c22d057ea9495db1e0fbf642a4cea2208164d85c46672990915232584fe/cffi-1.10.0-cp26-cp26m-win32.whl'
                'https://files.pythonhosted.org/packages/0a/62/8cf4b5ee4aa74444fa6238a8fd8673bca1ac81f29ae525fb93e441ebf599/cryptography-2.0.3-cp26-cp26m-win32.whl'
            )
        }
        $pyopensslPackages = @()
        Foreach ($url in $pipPy26Deps) {
            $filename = $deps + '\' + ([uri]$url).Segments[-1]
            & curl.exe -sS $url -o $filename
            $pyopensslPackages += $filename
        }
        & pip install --upgrade $pyopensslPackages
        & pip --version
    }

    & pip install $pipCommonPackages $pipPackages.$svnBranch

    if ($pyIsConda) {
	& conda.exe install -qy $condaCommonPackages
    }

    if ($usingMysql) {
        #
        # $TRAC_TEST_DB_URI="mysql://tracuser:password@localhost/trac"
        #

        # Conda provides MySQL-python support for Windows (x86 and x64)

        & conda.exe install -qy mysql-python

        Add-AppveyorMessage -Message "1.1. mysql-python package installed" `
          -Category Information
    }
    elseif ($usingPostgresql) {
        #
        # $TRAC_TEST_DB_URI=
        # "postgres://tracuser:password@localhost/trac?schema=tractest"
        #

        & pip install psycopg2

        Add-AppveyorMessage -Message "1.1. psycopg2 package installed" `
          -Category Information
    }

    & pip list --format=columns

    # Prepare local Makefile.cfg

    ".uri = $env:TRAC_TEST_DB_URI" | Out-File -Encoding ASCII 'Makefile.cfg'

    # Note 1: echo would create an UCS-2 file with a BOM, make.exe
    #         doesn't appreciate...

    # Note 2: we can't do more at this stage, as the services
    #         (MySQL/PostgreSQL) are not started yet.
}



function Trac-Build {

    Write-Step -Name BUILD -Skip $skipBuild

    if ($skipBuild) {
        return
    }

    # Preparing database if needed

    if ($usingMysql) {
        #
        # $TRAC_TEST_DB_URI="mysql://tracuser:password@localhost/trac"
        #
        $env:MYSQL_PWD = $mysqlPwd
        $env:Path      = "$mysqlHome\bin;$($env:Path)"

        Write-Host "Creating 'trac' MySQL database with user 'tracuser'"

        & mysql.exe -u root -e `
          ('CREATE DATABASE trac DEFAULT CHARACTER SET utf8mb4' +
           ' COLLATE utf8mb4_bin')
        & mysql.exe -u root -e `
          'CREATE USER tracuser@localhost IDENTIFIED BY ''password'';'
        & mysql.exe -u root -e `
          'GRANT ALL ON trac.* TO tracuser@localhost; FLUSH PRIVILEGES;'

        Add-AppveyorMessage -Message "2.1. MySQL database created" `
          -Category Information
    }
    elseif ($usingPostgresql) {
        #
        # $TRAC_TEST_DB_URI=
        # "postgres://tracuser:password@localhost/trac?schema=tractest"
        #
        $env:PGUSER     = $pgUser
        $env:PGPASSWORD = $pgPassword
        $env:Path       = "$pgHome\bin;$($env:Path)"

        Write-Host "Creating 'trac' PostgreSQL database with user 'tracuser'"

        & psql.exe -U postgres -c `
          ('CREATE USER tracuser NOSUPERUSER NOCREATEDB CREATEROLE' +
           ' PASSWORD ''password'';')
        & psql.exe -U postgres -c `
          'CREATE DATABASE trac OWNER tracuser;'

        Add-AppveyorMessage -Message "2.1. PostgreSQL database created" `
          -Category Information
    }

    Write-Host "make compile"

    # compile: if there are fuzzy catalogs, an error message will be
    # generated on stderr.

    & make.exe Trac.egg-info compile 2>&1 | Tee-Object -Variable make

    $stderr = $make | ?{ $_ -is [System.Management.Automation.ErrorRecord] }
    $stdout = $make | ?{ $_ -isnot [System.Management.Automation.ErrorRecord] }

    if ($LastExitCode) {
        Add-AppveyorMessage -Message "2.2. make compile produced errors" `
          -Category Error -Details ($stderr -join "`n")
    }
    elseif ($stderr) {
        Add-AppveyorMessage -Message "2.2. make compile produced warnings" `
          -Category Warning -Details ($stderr -join "`n")
    }
    else {
        Add-AppveyorMessage -Message "2.2. make compile was successful" `
          -Category Information
    }
}



function Trac-Tests {

    Write-Step -Name TESTS -Skip $skipTests

    $config = "$pyHome - $env:TRAC_TEST_DB_URI"

    if ("$env:TRAC_TEST_DB_URI" -eq '') {
        $config += 'sqlite :memory:'
    }

    function Make-Test([string]$goal, [string]$name, [ref]$code) {
        if ($skipTests) {
            Add-AppveyorTest -Name $name -Outcome Skipped
            return
        }

        Write-Host "make $goal"

        Add-AppveyorTest -Name $name -Outcome Running
        & make.exe $goal 2>&1 | Tee-Object -Variable make

        # Determine outcome Passed or Failed
        $outcome = 'Passed'
        if ($LastExitCode) {
            $outcome = 'Failed'
            $code.value += 1
        }

        $stderr = $make |
          ?{ $_ -is [System.Management.Automation.ErrorRecord] }
        $stdout = $make |
          ?{ $_ -isnot [System.Management.Automation.ErrorRecord] }

        # Retrieve duration of the tests

        $msecs = 0
        if ([string]$stderr -match "Ran \d+ tests in (\d+\.\d+)s") {
            $secs = $matches[1]
            $msecs = [math]::Round([float]$secs * 1000)
        }

        Update-AppveyorTest -Name $name -Outcome $outcome `
          -StdOut ($stdout -join "`n") -StdErr ($stderr -join '') `
          -Duration $msecs
    }

    $exit = $fexit = 0

    #
    # Running unit-tests
    #

    Make-Test -Goal unit-test -Name "Unit tests for $config" `
      -Code ([ref]$exit)

    #
    # Running functional tests
    #

    Make-Test -Goal functional-test -Name "Functional tests for $config" `
      -Code ([ref]$fexit)

    if (-not $fexit -eq 0) {
        Write-Host "Saving functional logs in testenv.zip"
        & 7z.exe a testenv.zip testenv

        Push-AppveyorArtifact testenv.zip

        $exit = $fexit
    }

    if (-not $exit -eq 0) {
        Write-Host "Exiting with code $exit"
        Exit $exit
    }

    if (-not $skipTests) {
        Write-Host "All tests passed."
    }

    #
    # Prepare release artifacts
    #

    & make.exe release-src wininst
}
